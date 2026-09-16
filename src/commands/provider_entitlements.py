"""The one writer of `<omh-home>/routing/providers.json`.

Two surfaces record what this machine's providers serve: the `omh setup`
interview, for a person at a terminal, and `omh model-chains provider set`,
for an install script or an agent -- a `--yes`, `--json`, or non-TTY setup
asks no provider question at all, so without the command the only way in is
hand-editing the file.

Both go through `write_provider_entitlements` here, which validates with
`parse_provider_entitlements` -- the reader's own rules, not a second copy --
before anything reaches disk. A document this module refuses to write is
exactly a document the reader would refuse to apply, so the two cannot drift
into a state where a write succeeds and the record is silently ignored.
"""

from __future__ import annotations

import json
from typing import Any

from ..local_store import atomic_write_text
from ..plugin_bundle.omh.hermes_delegation import (
    PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
    load_provider_entitlements,
    parse_provider_entitlements,
    provider_entitlements_path,
)

PROVIDER_RECORD_SCHEMA_VERSION = "provider_entitlement_record/v1"


def write_provider_entitlements(omh_home, document: dict[str, Any]) -> str:
    """Validate ``document`` through the reader's rules, then write it atomically.

    Raises ValueError with the reader's own status string when the document
    would not load, so a caller never writes a file the reader drops.
    """
    _parsed, status = parse_provider_entitlements(document)
    if status.startswith("invalid"):
        raise ValueError(status)
    path = provider_entitlements_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    return str(path)


def record_provider_kind(omh_home, provider_id: str, kind: str | None) -> dict[str, Any]:
    """Set (``kind``) or clear (``None``) one provider, leaving the rest alone.

    The record is read, one key changed, and the whole document written back,
    so `subscription_clis` and every other provider survive. Setting a kind
    also drops the id from `excluded_providers`: the operator naming what a
    provider serves and the record saying they cleared that same row are
    contradictory, and the recorded entry wins anyway. Clearing does not
    restore an exclusion, because the row simply goes back to being whatever
    detection finds.

    Idempotent: a `set` that changes nothing and a `clear` of an id that is
    not recorded both report `unchanged` and write no bytes, so an install
    script can run it on every run.
    """
    existing, status = load_provider_entitlements(omh_home)
    payload: dict[str, Any] = {
        "schema_version": PROVIDER_RECORD_SCHEMA_VERSION,
        "path": str(provider_entitlements_path(omh_home)),
        "provider": provider_id,
        "kind": kind,
        "document_status": status,
    }
    if status.startswith("invalid:"):
        # Rewriting here would throw away an operator document nobody has
        # read. The interview can replace it wholesale because a person is
        # watching the warning; a script is not.
        payload["status"] = "refused_invalid_document"
        return payload

    providers = dict(existing["providers"]) if existing else {}
    clis = list(existing["subscription_clis"]) if existing else []
    excluded = list(existing.get("excluded_providers", [])) if existing else []

    if kind is None:
        if provider_id not in providers:
            payload["status"] = "unchanged"
            return payload
        del providers[provider_id]
    else:
        if providers.get(provider_id) == kind and provider_id not in excluded:
            payload["status"] = "unchanged"
            return payload
        providers[provider_id] = kind
        excluded = [entry for entry in excluded if entry != provider_id]

    document: dict[str, Any] = {
        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
        "providers": providers,
        "subscription_clis": clis,
    }
    if excluded:
        document["excluded_providers"] = sorted(excluded)
    payload["path"] = write_provider_entitlements(omh_home, document)
    payload["status"] = "cleared" if kind is None else "recorded"
    payload["providers"] = dict(providers)
    return payload
