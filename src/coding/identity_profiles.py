"""User-defined identity profiles: prompt + model chain pairs.

`~/.omh/routing/identities.json` binds one user-named prompt to one ordered
model chain under the `omh_identity_profiles/v1` schema. Presence of the file
IS the opt-in: an absent file behaves exactly like today, and a malformed or
future-schema document reads the same as an absent one — a broken config must
never block a task.

Validation is per-identity: an invalid profile is dropped and named in
`rejected` so the remaining valid identities keep working. The returned
payload carries only validated data plus `fingerprint` metadata — never the
prompt text — so a frozen route record names its basis without storing user
prose.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Final, Mapping

from ..system.local_store import atomic_write_json, read_json_object_result
from .model_routing import (
    NON_GENERATIVE_MODEL_CLASS,
    model_class,
)

IDENTITY_PROFILES_SCHEMA_VERSION: Final[str] = "omh_identity_profiles/v1"

_IDENTITY_NAME_CHARSET: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789-_"
)
_EFFORT_CHARSET: Final[frozenset[str]] = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_MAX_IDENTITY_NAME_CHARS: Final[int] = 64
_MAX_PROMPT_BYTES: Final[int] = 4000
_MAX_CHAIN_ENTRIES: Final[int] = 8
_MAX_MODEL_ID_CHARS: Final[int] = 120
_MAX_EFFORT_CHARS: Final[int] = 32


def identity_profiles_path(omh_home: Path) -> Path:
    return Path(omh_home) / "routing" / "identities.json"


def _fingerprint(identities: Mapping[str, object]) -> dict[str, str]:
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":"))
    return {
        "source": "identities.json",
        "digest": sha256(canonical.encode("utf-8")).hexdigest()[:16],
    }


def _validated_chain_entry(
    entry: object, *, where: str, rejected: list[str]
) -> dict[str, str] | None:
    if not isinstance(entry, Mapping):
        rejected.append(f"{where}: chain entry must be an object with model_id")
        return None
    model_id = str(entry.get("model_id", "") or "").strip()
    # A leading `-` is rejected because selected_model lands in the spawned
    # CLI's argv as its own token: never allow a "model id" that would parse
    # as a flag there.
    if (
        not model_id
        or len(model_id) > _MAX_MODEL_ID_CHARS
        or model_id.startswith("-")
        or any(char.isspace() for char in model_id)
    ):
        rejected.append(
            f"{where}: model_id must be a non-empty token without whitespace or a leading '-'"
        )
        return None
    if model_class(model_id) == NON_GENERATIVE_MODEL_CLASS:
        rejected.append(
            f"{where}: model_id {model_id!r} is a {NON_GENERATIVE_MODEL_CLASS} model "
            "(it answers typed questions and cannot write code)"
        )
        return None
    effort = str(entry.get("reasoning_effort", "") or "").strip().casefold()
    if effort and (
        len(effort) > _MAX_EFFORT_CHARS or not set(effort) <= _EFFORT_CHARSET
    ):
        rejected.append(
            f"{where}: reasoning_effort {effort!r} is not an effort-shaped value"
        )
        return None
    return {"model_id": model_id, "reasoning_effort": effort}


def _validated_identity(
    name: str, raw: object, *, rejected: list[str]
) -> dict[str, object] | None:
    where = f"identity {name!r}"
    if not isinstance(raw, Mapping):
        rejected.append(f"{where}: profile must be an object")
        return None
    unknown = sorted(set(raw) - {"prompt", "model_chain"})
    if unknown:
        rejected.append(f"{where}: unsupported fields {unknown}")
        return None
    prompt = str(raw.get("prompt", "") or "").strip()
    if not prompt:
        rejected.append(f"{where}: prompt must be a non-empty string")
        return None
    prompt_bytes = len(prompt.encode("utf-8"))
    if prompt_bytes > _MAX_PROMPT_BYTES:
        rejected.append(
            f"{where}: prompt exceeds {_MAX_PROMPT_BYTES} UTF-8 bytes "
            f"({prompt_bytes} bytes)"
        )
        return None
    raw_chain = raw.get("model_chain")
    if not isinstance(raw_chain, (list, tuple)):
        rejected.append(f"{where}: model_chain must be a non-empty list")
        return None
    if not raw_chain:
        rejected.append(f"{where}: model_chain must not be empty")
        return None
    if len(raw_chain) > _MAX_CHAIN_ENTRIES:
        rejected.append(
            f"{where}: model_chain longer than {_MAX_CHAIN_ENTRIES} entries"
        )
        return None
    chain: list[dict[str, str]] = []
    for position, raw_entry in enumerate(raw_chain):
        validated = _validated_chain_entry(
            raw_entry,
            where=f"{where} chain entry {position}",
            rejected=rejected,
        )
        if validated is None:
            return None
        chain.append(validated)
    return {"prompt": prompt, "model_chain": tuple(chain)}


def read_identity_profiles_config(
    omh_home: Path,
    *,
    rejected_out: list[str] | None = None,
) -> dict[str, object] | None:
    """Return the validated identity profiles, or None when absent.

    The returned payload maps identity names to `{"prompt", "model_chain"}`
    pairs, plus `fingerprint` and `rejected` diagnostics. A document that
    validates down to nothing returns None so callers treat it exactly like
    an absent file; `rejected_out`, when given, still receives every rejection
    note so the operator can see why the identities were dropped.
    """
    document, _error = read_json_object_result(identity_profiles_path(omh_home))
    if not isinstance(document, dict):
        return None
    if document.get("schema_version") != IDENTITY_PROFILES_SCHEMA_VERSION:
        return None
    raw_identities = document.get("identities")
    if not isinstance(raw_identities, Mapping):
        return None
    rejected: list[str] = []
    identities: dict[str, dict[str, object]] = {}
    for raw_name, raw_profile in raw_identities.items():
        name = str(raw_name or "").strip()
        if (
            not name
            or len(name) > _MAX_IDENTITY_NAME_CHARS
            or not set(name) <= _IDENTITY_NAME_CHARSET
        ):
            rejected.append(
                f"identity {raw_name!r}: name must match "
                f"[a-z0-9_-] and be at most {_MAX_IDENTITY_NAME_CHARS} chars"
            )
            continue
        validated = _validated_identity(name, raw_profile, rejected=rejected)
        if validated is not None:
            identities[name] = validated
    if rejected_out is not None:
        rejected_out.extend(rejected)
    if not identities:
        return None
    return {
        "schema_version": IDENTITY_PROFILES_SCHEMA_VERSION,
        "identities": identities,
        "fingerprint": _fingerprint(identities),
        "rejected": rejected,
    }


def _raw_document(omh_home: Path) -> dict[str, object]:
    """Return the on-disk document for editing; raise on one this code does not own.

    An existing file the writers do not recognize (different schema_version,
    non-object identities, unparseable JSON) is never overwritten — losing a
    hand-written or future-versioned config on a `set`/`clear` would be silent
    data loss.
    """
    path = identity_profiles_path(omh_home)
    if not path.exists():
        return {"schema_version": IDENTITY_PROFILES_SCHEMA_VERSION, "identities": {}}
    document, error = read_json_object_result(path)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == IDENTITY_PROFILES_SCHEMA_VERSION
        and isinstance(document.get("identities"), dict)
    ):
        return document
    raise ValueError(
        f"refusing to edit {path}: the existing file is not a recognized "
        f"{IDENTITY_PROFILES_SCHEMA_VERSION} document"
        + (f" ({error})" if error else "")
        + "; fix or remove it first"
    )


def set_identity_profile(
    omh_home: Path,
    name: str,
    *,
    prompt: str,
    model_chain: list[Mapping[str, str]],
) -> dict[str, object]:
    """Write one identity profile; raises ValueError on bad input."""
    normalized = str(name or "").strip()
    if (
        not normalized
        or len(normalized) > _MAX_IDENTITY_NAME_CHARS
        or not set(normalized) <= _IDENTITY_NAME_CHARSET
    ):
        raise ValueError(
            f"identity name must match [a-z0-9_-] and be at most "
            f"{_MAX_IDENTITY_NAME_CHARS} chars"
        )
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("prompt must be a non-empty string")
    if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
        raise ValueError(f"prompt exceeds {_MAX_PROMPT_BYTES} UTF-8 bytes")
    if not model_chain or len(model_chain) > _MAX_CHAIN_ENTRIES:
        raise ValueError(f"a chain needs 1..{_MAX_CHAIN_ENTRIES} entries")
    rejected: list[str] = []
    validated = [
        _validated_chain_entry(
            entry, where=f"chain entry {position}", rejected=rejected
        )
        for position, entry in enumerate(model_chain)
    ]
    if any(entry is None for entry in validated):
        raise ValueError("; ".join(rejected))
    document = _raw_document(omh_home)
    identities = document["identities"]
    assert isinstance(identities, dict)
    identities[normalized] = {
        "prompt": prompt,
        "model_chain": [dict(entry) for entry in validated if entry],
    }
    atomic_write_json(identity_profiles_path(omh_home), document)
    return {
        "identity": normalized,
        "path": str(identity_profiles_path(omh_home)),
    }


def clear_identity_profile(omh_home: Path, name: str) -> dict[str, object]:
    """Remove one identity profile."""
    normalized = str(name or "").strip()
    document = _raw_document(omh_home)
    identities = document["identities"]
    assert isinstance(identities, dict)
    removed = normalized in identities
    if removed:
        del identities[normalized]
        atomic_write_json(identity_profiles_path(omh_home), document)
    return {
        "identity": normalized,
        "removed": removed,
        "path": str(identity_profiles_path(omh_home)),
    }
