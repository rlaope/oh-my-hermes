"""Immutable, content-addressed role-context packs for coding handoffs.

A role-context pack is the reviewed guidance that travels with one coding
handoff, named by the sha256 of its own content.

Composition is closed. A pack is built only from guidance OMH already
approved -- the ``handoff_context_pack/v1`` items and the
``project_memory_recall_pack/v1`` records that survived their own eligibility
gates. Nothing else enters, so a pack can never be a channel for unreviewed
conversation content.

Identity covers order. The hash is taken over the ordered per-record hashes
plus the pack's own metadata, so record ORDER is part of the name. The recall
builder's ordering is meaningful -- pinned anchors lead, then relevance -- and
two orders of the same records are two different guidance packs.

Immutability is structural, not conventional. There is no writer that accepts
a destination: ``write_role_context_pack`` derives the path from the content
hash, so "editing" a pack necessarily writes a different file and leaves the
accepted one byte-identical. ``read_role_context_pack`` recomputes the hash
from the bytes it loaded and refuses a mismatch, so an out-of-band edit cannot
answer to the old name either. There is no update, patch, or append entry
point in this module, and the pack contract carries no mutable field.

The pack is executor-neutral by construction. It carries no owner field, so
Codex, Claude Code, Hermes, and generic executor profiles consume the same
contract and -- given the same guidance -- the same hash. Owner-specific
selection happens earlier, through the perspective lens
``memory_recall_pack_for_handoff`` and ``build_handoff_context_pack`` already
apply: the role decides which records are eligible, the content decides the
name.

Reason vocabulary is borrowed, never forked. An included record explains
itself with the reason code its own source surface already emits -- a recall
record's ``eligibility_reason``, a context item's ``truth_level`` -- and this
module only renders those codes as human text. ``tests/test_role_context_packs.py``
fails when a rendered code is not one of those surfaces' codes.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, read_json_object
from ..paths import OmhPaths
from ..system.metadata_safety import is_secret_value_shaped
from .memory import (
    HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
    PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
    freshness_reason_detail,
)


ROLE_CONTEXT_PACK_SCHEMA_VERSION = "role_context_pack/v1"
ROLE_CONTEXT_PACK_DIFF_SCHEMA_VERSION = "role_context_pack_diff/v1"

# The handoff field that pins one pack. The pin is a value the handoff itself
# carries, so a stored handoff still names its pack after the store is gone.
ROLE_CONTEXT_PACK_HASH_FIELD = "role_context_pack_hash"
ROLE_CONTEXT_PACK_FIELD = "role_context_pack"

# The only two origins a pack record may come from. Both are reviewed OMH
# guidance surfaces that already ran their own eligibility and conflict gates.
ROLE_CONTEXT_PACK_ORIGINS = (HANDOFF_CONTEXT_PACK_SCHEMA_VERSION, PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION)

ROLE_CONTEXT_PACK_CLAIM_BOUNDARY = (
    "Role context packs name reviewed OMH guidance by content hash; they are prepared context, "
    "not execution, review, CI, merge, or Hermes internal-memory evidence."
)
ROLE_CONTEXT_PACK_DIFF_CLAIM_BOUNDARY = (
    "A role context pack diff describes a proposed guidance change before acceptance; "
    "it is not execution, review, CI, or merge evidence."
)

_ROLE_CONTEXT_PACK_KEYS = {
    "schema_version",
    "pack_hash",
    "scope",
    "records",
    "record_count",
    "redaction_policy",
    "claim_boundary",
}
_ROLE_CONTEXT_PACK_RECORD_KEYS = ("position", "record_id", "record_hash", "origin", "label", "reason_code", "reason")
_ROLE_CONTEXT_PACK_SCOPE_KEYS = {"kind", "ref"}
_DEFAULT_SCOPE = {"kind": "project", "ref": "default"}

# A pack hash is also a filename, so it is matched before it reaches a path.
_PACK_HASH = re.compile(r"^[0-9a-f]{64}$")
# Ids and labels are metadata refs, not free text, so they are length-bounded.
# Deliberately not a character-class match: a wrapper-supplied context pack may
# use any id shape its own validator accepted, and rejecting one here would
# fail an otherwise valid handoff over a field this module never puts in a
# path. The path is built from the pack hash, which IS character-matched above.
_MAX_PACK_REF_LENGTH = 160

# Human text for the one recall-pack eligibility code an INCLUDED record can
# carry. Every other eligibility code renders through
# `freshness_reason_detail`, which reads the recall pack's own table, so this
# module never grows a second vocabulary.
_ELIGIBLE_REASON_CODE = "eligible"
_ELIGIBLE_REASON_TEXT = "Reviewed project memory that passed replay evaluation for this handoff."
# Human text for the source truth levels `handoff_context_pack/v1` items carry.
# The codes are `SOURCE_TRUTH_LEVELS`' own values; a guard test fails when the
# two sets drift apart.
TRUTH_LEVEL_REASON_TEXT = {
    "observed_evidence": "Observed runtime evidence recorded in the OMH run ledger.",
    "runtime_index_state": "Current OMH runtime index state.",
    "chat_decision_state": "A plan or decision the wrapper session already recorded.",
    "setup_evidence": "Target topology observed during OMH setup.",
    "preference_default": "A configured OMH setup preference.",
    "approved_context": "Reviewed and approved OMH project guidance.",
    "durable_knowledge": "Durable project knowledge kept in OMH wiki notes.",
    "capability_hint": "A catalog capability hint, not observed evidence.",
    "supplied_hint": "Context the wrapper supplied for this task.",
}
_UNKNOWN_REASON_TEXT = "Included as reviewed OMH guidance; its source surface gave no reason code."


def build_role_context_pack(
    *,
    context_pack: dict[str, Any] | None = None,
    memory_recall_pack: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    excluded_record_ids: tuple[str, ...] | list[str] = (),
) -> dict[str, object]:
    """Compose one immutable pack from the guidance already approved for a handoff.

    Deterministic by construction: no wall clock, no store read, no ordering
    that depends on dict iteration. Call it twice with the same guidance and
    the same hash comes back; drop a record, reorder the source pack, or edit
    a summary and a different hash comes back. That is the whole of AC2 --
    there is no way to express "change this pack", only "build the next one".

    ``excluded_record_ids`` is the operator adjustment affordance the Hermes
    pre-accept review needs. It does not edit anything: it selects a different
    record set, which by definition names a different pack.
    """
    dropped = {str(record_id) for record_id in excluded_record_ids}
    records: list[dict[str, object]] = []
    for entry in _context_pack_entries(context_pack):
        if entry["record_id"] not in dropped:
            records.append(entry)
    for entry in _recall_pack_entries(memory_recall_pack):
        if entry["record_id"] not in dropped:
            records.append(entry)
    positioned = [
        {
            "position": index,
            "record_id": entry["record_id"],
            "record_hash": entry["record_hash"],
            "origin": entry["origin"],
            "label": entry["label"],
            "reason_code": entry["reason_code"],
            "reason": entry["reason"],
        }
        for index, entry in enumerate(records)
    ]
    pack: dict[str, object] = {
        "schema_version": ROLE_CONTEXT_PACK_SCHEMA_VERSION,
        "pack_hash": "",
        "scope": _pack_scope(scope, context_pack, memory_recall_pack),
        "records": positioned,
        "record_count": len(positioned),
        "redaction_policy": "metadata_only",
        "claim_boundary": ROLE_CONTEXT_PACK_CLAIM_BOUNDARY,
    }
    pack["pack_hash"] = role_context_pack_hash(pack)
    errors = validate_role_context_pack(pack, label="role_context_pack")
    if errors:
        raise ValueError("; ".join(errors))
    return pack


def role_context_pack_hash(pack: dict[str, Any]) -> str:
    """Content address of a pack: sha256 over every field except the name itself.

    The ordered ``records`` list is inside the seed, so both the record hashes
    and their order are part of the identity. Everything else in the pack is in
    the seed too -- the seed is built by exclusion, so a field added to the
    contract later cannot quietly sit outside the pack's identity.
    """
    seed = {key: value for key, value in pack.items() if key != "pack_hash"}
    return _canonical_digest(seed)


def role_context_pack_is_empty(pack: dict[str, Any]) -> bool:
    """An empty pack is a real pack that names no guidance.

    Distinct from an absent pack: absence means nothing was composed, while an
    empty pack is an accepted statement that this handoff travels with no
    reviewed guidance, and it has a hash that says so.
    """
    return isinstance(pack, dict) and not pack.get("records")


def pin_role_context_pack(handoff: Any, pack: dict[str, Any]) -> None:
    """Bind one pack to one handoff: the pin value plus the resolvable pack."""
    if not isinstance(handoff, dict):
        return
    errors = validate_role_context_pack(pack, label="role_context_pack")
    if errors:
        raise ValueError("; ".join(errors))
    handoff[ROLE_CONTEXT_PACK_HASH_FIELD] = str(pack["pack_hash"])
    handoff[ROLE_CONTEXT_PACK_FIELD] = pack


def validate_role_context_pack(value: Any, *, label: str = "role_context_pack") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    extra_keys = sorted(set(value) - _ROLE_CONTEXT_PACK_KEYS)
    if extra_keys:
        errors.append(f"{label} has unsupported keys: {extra_keys}")
    if value.get("schema_version") != ROLE_CONTEXT_PACK_SCHEMA_VERSION:
        errors.append(f"{label} schema_version must be {ROLE_CONTEXT_PACK_SCHEMA_VERSION}")
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label} redaction_policy must be metadata_only")
    if not isinstance(value.get("claim_boundary"), str) or not value.get("claim_boundary"):
        errors.append(f"{label} claim_boundary must be a non-empty string")
    _validate_pack_scope(value.get("scope"), errors, f"{label}.scope")
    errors.extend(_validate_pack_records(value.get("records"), f"{label}.records"))
    records = value.get("records")
    if isinstance(records, list) and value.get("record_count") != len(records):
        errors.append(f"{label}.record_count must equal the number of records")
    pack_hash = value.get("pack_hash")
    if not isinstance(pack_hash, str) or not _PACK_HASH.match(pack_hash):
        errors.append(f"{label}.pack_hash must be a lowercase sha256 hex digest")
    elif not errors and pack_hash != role_context_pack_hash(value):
        errors.append(f"{label}.pack_hash does not match the pack content")
    return errors


def validate_role_context_pack_pin(handoff: Any, label: str) -> list[str]:
    """A pinned hash and the pack it references must agree, or it is an error.

    Silence when the handoff carries neither, so a legacy handoff prepared
    before packs existed still validates. Once either half is present, both
    halves are required and the pin must recompute from the pack -- a pin that
    does not match its pack is never a warning.
    """
    if not isinstance(handoff, dict):
        return [f"{label} must be an object"]
    pinned = handoff.get(ROLE_CONTEXT_PACK_HASH_FIELD)
    has_hash = ROLE_CONTEXT_PACK_HASH_FIELD in handoff
    has_pack = ROLE_CONTEXT_PACK_FIELD in handoff
    if not has_hash and not has_pack:
        return []
    errors: list[str] = []
    if not has_hash:
        errors.append(f"{label} carries {ROLE_CONTEXT_PACK_FIELD} without naming {ROLE_CONTEXT_PACK_HASH_FIELD}")
    if not has_pack:
        errors.append(f"{label} pins {ROLE_CONTEXT_PACK_HASH_FIELD} without a resolvable {ROLE_CONTEXT_PACK_FIELD}")
    if not isinstance(pinned, str) and has_hash:
        errors.append(f"{label} {ROLE_CONTEXT_PACK_HASH_FIELD} must be a string")
    if has_pack:
        pack_errors = validate_role_context_pack(handoff.get(ROLE_CONTEXT_PACK_FIELD), label=f"{label} {ROLE_CONTEXT_PACK_FIELD}")
        errors.extend(pack_errors)
        pack = handoff.get(ROLE_CONTEXT_PACK_FIELD)
        if not pack_errors and isinstance(pack, dict) and isinstance(pinned, str) and pinned != pack.get("pack_hash"):
            errors.append(f"{label} {ROLE_CONTEXT_PACK_HASH_FIELD} does not match the attached pack")
    return errors


def validate_accepted_role_context(handoff: Any, label: str) -> list[str]:
    """Acceptance gate: an accepted coding handoff names exactly one pack hash.

    Preparing a handoff and accepting one are different acts. A prepared
    handoff may carry no guidance at all; an accepted one must say which
    immutable pack shaped it, even when that pack is empty.
    """
    if not isinstance(handoff, dict):
        return [f"{label} must be an object"]
    errors = validate_role_context_pack_pin(handoff, label)
    if ROLE_CONTEXT_PACK_HASH_FIELD not in handoff:
        errors.append(f"{label} must name exactly one {ROLE_CONTEXT_PACK_HASH_FIELD} before acceptance")
    return errors


def diff_role_context_packs(previous: Any, current: Any) -> dict[str, object]:
    """Render additions, removals, reorders, and stale records before acceptance.

    Pure projection over two packs. It never writes and never resolves the
    store, so showing a user what would change costs nothing and cannot alter
    the pack they have already accepted.
    """
    previous_records = _diff_record_index(previous)
    current_records = _diff_record_index(current)
    added = [_diff_entry(entry) for record_id, entry in current_records.items() if record_id not in previous_records]
    removed = [_diff_entry(entry) for record_id, entry in previous_records.items() if record_id not in current_records]
    reordered = [
        {
            "record_id": record_id,
            "previous_position": int(previous_records[record_id].get("position", 0)),
            "current_position": int(entry.get("position", 0)),
        }
        for record_id, entry in current_records.items()
        if record_id in previous_records and previous_records[record_id].get("position") != entry.get("position")
    ]
    stale = [_diff_entry(entry) for entry in current_records.values() if _is_stale_reason(str(entry.get("reason_code", "")))]
    previous_hash = str(previous.get("pack_hash", "")) if isinstance(previous, dict) else ""
    current_hash = str(current.get("pack_hash", "")) if isinstance(current, dict) else ""
    return {
        "schema_version": ROLE_CONTEXT_PACK_DIFF_SCHEMA_VERSION,
        "previous_pack_hash": previous_hash,
        "current_pack_hash": current_hash,
        "changed": previous_hash != current_hash,
        "added": added,
        "removed": removed,
        "reordered": reordered,
        "stale": stale,
        "claim_boundary": ROLE_CONTEXT_PACK_DIFF_CLAIM_BOUNDARY,
    }


def role_context_pack_path(paths: OmhPaths, pack_hash: str) -> Path:
    """The store location of a pack, derived from its content hash alone.

    There is no variant of this that takes a caller-chosen name. That is what
    makes the store append-only in practice: a different pack is a different
    hash is a different file.
    """
    if not _PACK_HASH.match(str(pack_hash)):
        raise ValueError(f"unsafe role context pack hash: {pack_hash!r}")
    return paths.role_context_packs_dir / f"{pack_hash}.json"


def write_role_context_pack(paths: OmhPaths, pack: dict[str, Any]) -> Path:
    """Store a pack under its own content hash. Rewriting is a no-op, never an edit.

    The destination is a function of the content, so this cannot overwrite a
    different pack. When the file already exists it is left exactly as it is:
    equal content would produce equal bytes, and unequal content would have
    produced a different path.
    """
    errors = validate_role_context_pack(pack, label="role_context_pack")
    if errors:
        raise ValueError("; ".join(errors))
    path = role_context_pack_path(paths, str(pack["pack_hash"]))
    if path.exists():
        return path
    atomic_write_json(path, dict(pack), private=True)
    return path


def read_role_context_pack(paths: OmhPaths, pack_hash: str) -> dict[str, Any] | None:
    """Resolve a pinned hash back to its pack, or None when the store lacks it.

    The loaded bytes are re-hashed and the name is re-checked, so a pack edited
    out of band cannot keep answering to the hash a handoff pinned.
    """
    path = role_context_pack_path(paths, pack_hash)
    if not path.exists():
        return None
    pack = read_json_object(path)
    if not isinstance(pack, dict):
        raise ValueError(f"role context pack {pack_hash} is not a JSON object")
    errors = validate_role_context_pack(pack, label=f"role context pack {pack_hash}")
    if errors:
        raise ValueError("; ".join(errors))
    if str(pack.get("pack_hash", "")) != str(pack_hash):
        raise ValueError(f"role context pack {pack_hash} does not answer to its stored name")
    return pack


def _context_pack_entries(context_pack: Any) -> list[dict[str, str]]:
    if not isinstance(context_pack, dict):
        return []
    entries: list[dict[str, str]] = []
    for item in context_pack.get("included_context", []) or []:
        if not isinstance(item, dict):
            continue
        reason_code = _context_item_reason_code(item)
        entries.append(
            _entry(
                origin=HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
                record_id=str(item.get("item_id", "")),
                label=str(item.get("key", "")),
                summary=str(item.get("summary", "")),
                source=str(item.get("source", "")),
                reason_code=reason_code,
            )
        )
    return entries


def _recall_pack_entries(memory_recall_pack: Any) -> list[dict[str, str]]:
    if not isinstance(memory_recall_pack, dict):
        return []
    entries: list[dict[str, str]] = []
    for item in memory_recall_pack.get("included_records", []) or []:
        if not isinstance(item, dict):
            continue
        entries.append(
            _entry(
                origin=PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
                record_id=str(item.get("record_id", "")),
                label=str(item.get("record_type", "")),
                summary=str(item.get("summary", "")),
                source=str(item.get("source", "")),
                reason_code=str(item.get("eligibility_reason", "") or ""),
            )
        )
    return entries


def _context_item_reason_code(item: dict[str, Any]) -> str:
    """A context item explains itself with the code its own surface emitted.

    Memory-sourced items already carry a replay evaluation, so their recall
    eligibility code wins; everything else states its source truth level.
    """
    evaluation = item.get("replay_evaluation")
    if isinstance(evaluation, dict) and str(evaluation.get("reason_code", "")):
        return str(evaluation["reason_code"])
    return str(item.get("truth_level", "") or "")


def _entry(*, origin: str, record_id: str, label: str, summary: str, source: str, reason_code: str) -> dict[str, str]:
    # The summary is inside the record hash but never inside the pack: the pack
    # is a manifest of what shaped the handoff, and the guidance text stays in
    # the surface it came from. Editing a summary therefore still mints a new
    # pack without the pack duplicating every summary it names.
    return {
        "origin": origin,
        "record_id": record_id,
        "label": label,
        "reason_code": reason_code,
        "reason": _reason_text(reason_code),
        "record_hash": _canonical_digest(
            {
                "origin": origin,
                "record_id": record_id,
                "label": label,
                "summary": summary,
                "source": source,
                "reason_code": reason_code,
            }
        ),
    }


def _reason_text(reason_code: str) -> str:
    code = str(reason_code)
    if code == _ELIGIBLE_REASON_CODE:
        return _ELIGIBLE_REASON_TEXT
    if code in TRUTH_LEVEL_REASON_TEXT:
        return TRUTH_LEVEL_REASON_TEXT[code]
    return freshness_reason_detail(code) or _UNKNOWN_REASON_TEXT


def _is_stale_reason(reason_code: str) -> bool:
    """Stale means the recall pack's own freshness vocabulary claimed it."""
    return bool(freshness_reason_detail(reason_code))


def _pack_scope(scope: Any, context_pack: Any, memory_recall_pack: Any) -> dict[str, str]:
    for candidate in (scope, _pack_field(context_pack, "scope"), _pack_field(memory_recall_pack, "scope")):
        if isinstance(candidate, dict) and str(candidate.get("kind", "")) and str(candidate.get("ref", "")):
            return {"kind": str(candidate["kind"]), "ref": str(candidate["ref"])}
    return dict(_DEFAULT_SCOPE)


def _pack_field(pack: Any, key: str) -> Any:
    return pack.get(key) if isinstance(pack, dict) else None


def _validate_pack_scope(value: Any, errors: list[str], label: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    extra_keys = sorted(set(value) - _ROLE_CONTEXT_PACK_SCOPE_KEYS)
    if extra_keys:
        errors.append(f"{label} has unsupported keys: {extra_keys}")
    for key in ("kind", "ref"):
        if not isinstance(value.get(key), str) or not value.get(key):
            errors.append(f"{label}.{key} must be a non-empty string")


def _validate_pack_records(value: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"{label} must be a list"]
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        # Key SET, never key order: a stored pack is read back through
        # `json.dumps(sort_keys=True)`, so insertion order does not survive the
        # round trip. Record ORDER is carried by `position`, which is checked
        # below and is inside the hash seed.
        if set(item) != set(_ROLE_CONTEXT_PACK_RECORD_KEYS):
            errors.append(f"{item_label} must carry exactly {sorted(_ROLE_CONTEXT_PACK_RECORD_KEYS)}")
            continue
        if item.get("position") != index:
            errors.append(f"{item_label}.position must equal its index")
        if item.get("origin") not in ROLE_CONTEXT_PACK_ORIGINS:
            errors.append(f"{item_label}.origin must be one of {list(ROLE_CONTEXT_PACK_ORIGINS)}")
        if not isinstance(item.get("record_hash"), str) or not _PACK_HASH.match(str(item.get("record_hash", ""))):
            errors.append(f"{item_label}.record_hash must be a lowercase sha256 hex digest")
        for key in ("record_id", "label", "reason_code", "reason"):
            if not isinstance(item.get(key), str):
                errors.append(f"{item_label}.{key} must be a string")
        for key in ("record_id", "label"):
            text = str(item.get(key, ""))
            if len(text) > _MAX_PACK_REF_LENGTH or is_secret_value_shaped(text):
                errors.append(f"{item_label}.{key} must be a bounded, non-credential metadata reference")
        if not str(item.get("record_id", "")):
            errors.append(f"{item_label}.record_id must be a non-empty string")
    return errors


def _diff_record_index(pack: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(pack, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for item in pack.get("records", []) or []:
        if isinstance(item, dict) and str(item.get("record_id", "")):
            index[str(item["record_id"])] = item
    return index


def _diff_entry(entry: dict[str, Any]) -> dict[str, str]:
    return {
        "record_id": str(entry.get("record_id", "")),
        "origin": str(entry.get("origin", "")),
        "reason_code": str(entry.get("reason_code", "")),
        "reason": str(entry.get("reason", "")),
    }


def _canonical_digest(payload: Any) -> str:
    """Deterministic sha256 over metadata, without going through JSON text.

    Three properties the digest needs and a JSON dump does not reliably give:

    * Every value is type-tagged, so the string ``"1"`` and the integer ``1``
      can never hash alike.
    * Every string is length-prefixed, so no separator can be forged from
      inside a value -- two adjacent fields cannot be rearranged into the same
      byte sequence.
    * Mapping keys are sorted and list order is preserved, which is exactly the
      identity this pack wants: dict insertion order does not survive a store
      round trip, while record ORDER is meaningful and must.

    Not going through `json.dumps` also keeps the content address independent
    of that function's escaping and separator choices, which are presentation
    decisions this hash must never inherit.
    """
    digest = hashlib.sha256()
    _feed_canonical(digest, payload)
    return digest.hexdigest()


def _feed_canonical(digest: Any, value: Any) -> None:
    if isinstance(value, bool):
        digest.update(b"b")
        _feed_text(digest, "1" if value else "0")
    elif isinstance(value, int):
        digest.update(b"i")
        _feed_text(digest, str(value))
    elif isinstance(value, str):
        digest.update(b"s")
        _feed_text(digest, value)
    elif value is None:
        digest.update(b"n")
    elif isinstance(value, (list, tuple)):
        digest.update(b"l")
        _feed_text(digest, str(len(value)))
        for item in value:
            _feed_canonical(digest, item)
    elif isinstance(value, dict):
        digest.update(b"d")
        _feed_text(digest, str(len(value)))
        for key in sorted(str(item) for item in value):
            digest.update(b"k")
            _feed_text(digest, key)
            _feed_canonical(digest, value[key])
    else:
        raise ValueError(f"role context pack content must be scalar metadata, got {type(value).__name__}")


def _feed_text(digest: Any, text: str) -> None:
    raw = text.encode("utf-8")
    digest.update(f"{len(raw)}:".encode("ascii"))
    digest.update(raw)
