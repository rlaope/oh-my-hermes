"""User-defined identity profiles: the plugin-bundle half.

`omh.coding.identity_profiles` owns the document contract — schema, full
validation, fingerprint, atomic writes. This module is the read-only view the
standalone plugin bundle can carry: the bundle ships into
`$HERMES_HOME/plugins` and cannot import `src/coding` (the same boundary that
keeps `hermes_delegation.py`'s chains embedded with a parity gate).

What the hook needs is narrow: given an explicit `[omh-identity:<name>]`
marker, is there a validated identity of that name, and what is its prompt.
The reader still applies the full per-profile contract the canonical loader
applies: name, prompt, chain, and unknown fields. A prompt is never admitted
without the chain it belongs with. A document that is absent, unreadable, or
not a recognized `omh_identity_profiles/v1` object yields no identities at all.

The marker itself is parsed the way `omh_roles.ROLE_MARKER_RE` is — a
bounded, explicit token the person types, never inferred from ordinary words.
Selection comes only from text the person authored (the hook hands this the
same `person_text` the role marker already reads).
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re

from . import runtime_paths

IDENTITY_PROFILES_SCHEMA_VERSION = "omh_identity_profiles/v1"

# Same bounds the canonical loader enforces (`omh.coding.identity_profiles`):
# the name token is `[a-z0-9_-]{1,64}` and a prompt is at most 4000 UTF-8
# bytes. A name outside the token shape cannot be produced by the marker
# regex either, so a hostile config cannot turn the marker into a wider
# selector.
_IDENTITY_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_MAX_PROMPT_BYTES = 4000

# Chain bounds from the same contract: 1..8 entries, `model_id` a non-empty
# token (no whitespace, no leading `-`, <=120 chars) and `reasoning_effort`
# at most 32 chars of `[a-z0-9-]`. The canonical loader casefolds effort; so
# does this reader, so both sides agree on the same stored value.
_MAX_CHAIN_ENTRIES = 8
_MAX_MODEL_ID_CHARS = 120
_MAX_EFFORT_CHARS = 32
_EFFORT_CHARSET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")

IDENTITY_MARKER_RE = re.compile(r"\[omh-identity:([a-z0-9_-]{1,64})\]")


def extract_identity_marker(text: str) -> str:
    """The first identity marker in ``text``, or "" — duplicates are ignored."""
    match = IDENTITY_MARKER_RE.search(text or "")
    return match.group(1) if match else ""


def identity_profiles_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "routing" / "identities.json"


def read_identity_prompts(omh_home: str | Path | None = None) -> dict[str, str]:
    """Validated ``{name: prompt}`` from the user's identities document.

    Never raises: an absent, unreadable, or unrecognized document reads as
    empty, matching "the file being absent changes nothing". Admission is the
    same per-profile check the routing half uses, so a profile with an invalid
    chain or an unknown field contributes no prompt either.
    """
    validated = _validated_identity_document(omh_home)
    return {name: str(profile["prompt"]) for name, profile in validated.items()}


def identity_context_payload(
    identity: str, *, omh_home: str | Path | None = None
) -> dict[str, object]:
    """Bounded payload for one marker-selected identity.

    Same shape discipline as `role_context_payload`: a known identity carries
    its prompt under ``context``; an unknown one reports ``unknown_identity``
    with the names that would have worked — never a silent fallback onto a
    different identity. ``context`` is the only place prompt text appears.
    """
    name = str(identity or "").strip()
    prompts = read_identity_prompts(omh_home)
    prompt = prompts.get(name)
    if prompt is None:
        return {
            "schema_version": "omh_identity_context/v1",
            "status": "unknown_identity",
            "identity": name,
            "available_identities": sorted(prompts),
            "context": "",
            "claim_boundary": (
                "OMH identity context is user-configured prompt guidance only; "
                "it is not runtime delegation or execution evidence."
            ),
        }
    return {
        "schema_version": "omh_identity_context/v1",
        "status": "available",
        "identity": name,
        "available_identities": sorted(prompts),
        "context": prompt,
        "claim_boundary": (
            "OMH identity context is user-configured prompt guidance only; "
            "it is not runtime delegation or execution evidence."
        ),
    }


# ── chain reading for the route tool ─────────────────────────────────────
#
# `omh_delegate_route` routes a child onto an identity's model chain, so it
# needs the chain view of the same document. The bundle cannot import
# `omh.coding.identity_profiles`, so this projects the same contract: a profile
# is admitted to the chain view only when it is fully valid under the canonical
# rules — name, prompt, unknown fields, and every chain entry. Both views read
# this one validator (`_validated_identity_document`). The canonical loader also
# refuses `non_generative` models; the only such family is `jev`, mirrored
# here as the model segment equal to `jev` or starting `jev-` after any
# provider path is stripped (the same spelling `model_family` reads).
#
# The fingerprint is `sha256(canonical JSON of the validated identities)`
# over `{prompt, model_chain}` pairs — the same canonical form the
# `omh.coding` loader computes, so a digest from this reader names the same
# basis as one from the resolver side.


def _is_non_generative(model_id: str) -> bool:
    """Mirror of `model_class`'s `jev` family check for the only non-generative family."""
    segment = model_id.strip().casefold().rsplit("/", 1)[-1]
    return segment == "jev" or segment.startswith("jev-")


def _validated_chain_entry(entry: object) -> dict[str, str] | None:
    if not isinstance(entry, Mapping):
        return None
    model_id = str(entry.get("model_id", "") or "").strip()
    if (
        not model_id
        or len(model_id) > _MAX_MODEL_ID_CHARS
        or model_id.startswith("-")
        or any(char.isspace() for char in model_id)
        or _is_non_generative(model_id)
    ):
        return None
    effort = str(entry.get("reasoning_effort", "") or "").strip().casefold()
    if effort and (len(effort) > _MAX_EFFORT_CHARS or not set(effort) <= _EFFORT_CHARSET):
        return None
    return {"model_id": model_id, "reasoning_effort": effort}


def _raw_identity_document(omh_home: str | Path | None) -> Mapping | None:
    path = identity_profiles_path(omh_home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != IDENTITY_PROFILES_SCHEMA_VERSION:
        return None
    identities = raw.get("identities")
    return identities if isinstance(identities, Mapping) else None


def _validated_identity_document(omh_home: str | Path | None) -> dict[str, dict[str, object]]:
    """Fully validated ``{name: {"prompt", "model_chain"}}``, or empty.

    The one view both the prompt hook and the route tool read. A profile is
    admitted only when every field passes; a failing profile drops alone.
    """
    identities = _raw_identity_document(omh_home)
    if not identities:
        return {}
    validated: dict[str, dict[str, object]] = {}
    for raw_name, raw_profile in identities.items():
        name = str(raw_name or "").strip()
        if not _IDENTITY_NAME_RE.fullmatch(name) or not isinstance(raw_profile, Mapping):
            continue
        if set(raw_profile) - {"prompt", "model_chain"}:
            continue
        prompt = str(raw_profile.get("prompt", "") or "").strip()
        if not prompt or len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            continue
        raw_chain = raw_profile.get("model_chain")
        if (
            not isinstance(raw_chain, (list, tuple))
            or not raw_chain
            or len(raw_chain) > _MAX_CHAIN_ENTRIES
        ):
            continue
        chain = [_validated_chain_entry(entry) for entry in raw_chain]
        if any(entry is None for entry in chain):
            continue
        validated[name] = {
            "prompt": prompt,
            "model_chain": tuple(entry for entry in chain if entry is not None),
        }
    return validated


def _fingerprint(identities: Mapping[str, object]) -> dict[str, str]:
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":"))
    return {
        "source": "identities.json",
        "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
    }


def read_identity_chains(omh_home: str | Path | None = None) -> dict[str, object]:
    """Validated identity chains and the document fingerprint, or empty.

    Returns ``{"identities": {name: tuple[(model_id, effort), ...]},
    "fingerprint": {"source": "identities.json", "digest": ...}}``. An
    absent, unreadable, or validates-to-nothing document yields empty
    ``identities`` and a ``None`` fingerprint — matching "absent file =
    old behavior". Never raises.
    """
    validated = _validated_identity_document(omh_home)
    if not validated:
        return {"identities": {}, "fingerprint": None}
    chains: dict[str, tuple[tuple[str, str], ...]] = {}
    for name, profile in validated.items():
        chain_entries = profile["model_chain"]
        chains[name] = tuple(
            (str(entry["model_id"]), str(entry["reasoning_effort"]))
            for entry in chain_entries  # type: ignore[union-attr]
        )
    return {"identities": chains, "fingerprint": _fingerprint(validated)}
