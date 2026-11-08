"""Metadata-only learning for explicit coding-owner choices.

This module owns the durable preference artifact and its pure transitions.  It
intentionally does not inspect request prose, model selection, executor results,
or timing data.  Integrating the resulting decision with wrapper routing is a
separate concern.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..system.local_store import atomic_write_json, read_json_object_result
from ..plugin_bundle.omh.owner_preference_record import (
    OWNER_PREFERENCE_EXCLUDED_SIGNALS,
    OWNER_PREFERENCE_EXPLICIT_CHOICE_PROVENANCES,
    OWNER_PREFERENCE_LEARNING_THRESHOLD,
    OWNER_PREFERENCE_PATH_SEGMENTS,
    OWNER_PREFERENCE_RECORD_TYPE,
    OWNER_PREFERENCE_SCHEMA_VERSION,
    valid_timestamp as _valid_timestamp,
    validate_owner_preference,
)
from ..system.metadata_safety import require_opaque_metadata_ref
from ..system.paths import OmhPaths


# The schema, its constants and its one validator live in the plugin bundle
# (`plugin_bundle/omh/owner_preference_record.py`).


@dataclass(frozen=True)
class OwnerPreferenceDecision:
    """The safe routing projection of learned owner state."""

    action: str
    reason_code: str
    reason: str
    route_family: str
    selected_owner: str
    evidence_count: int
    override_available: bool


def empty_owner_preference_state(*, updated_at: str = "") -> dict[str, Any]:
    """Return a valid state with no learned routes.

    ``updated_at`` is caller-supplied so construction and every transition stay
    deterministic.  An empty timestamp means no preference event has occurred.
    """
    if updated_at:
        _require_timestamp(updated_at, field="updated_at")
    return {
        "schema_version": OWNER_PREFERENCE_SCHEMA_VERSION,
        "record_type": OWNER_PREFERENCE_RECORD_TYPE,
        "privacy": {
            "mode": "metadata_only",
            "learning_source": "accepted_explicit_owner_choice",
            "excluded_signals": list(OWNER_PREFERENCE_EXCLUDED_SIGNALS),
        },
        "routes": {},
        "updated_at": updated_at,
    }


def owner_preference_decision(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    coding_delivery: bool = True,
    ulw: bool = True,
    named_owner: bool = False,
    multiple_owners: bool = False,
    authority_blocked: bool = False,
    owner_ready: bool = True,
    capability_fit: bool = True,
) -> OwnerPreferenceDecision:
    """Decide whether the request bypasses the owner question or has to ask it.

    A coding-owner choice counts only for the request it was made in, so the
    stored streak never selects an owner: without an owner named in this
    request, every gate ends in an explicit choice. The streak fields
    (`consecutive_accepted_explicit_choices`, `learned_at`) are inert history
    that no route reads; `evidence_count` reports them for status only.
    """
    family = require_opaque_metadata_ref(route_family, field="route_family")
    safe = _safe_state(state)
    route = safe["routes"].get(family)
    count = int(route["consecutive_accepted_explicit_choices"]) if route else 0

    if not coding_delivery:
        return _decision("bypass_owner_learning", "non_coding_workflow", family, count)
    if not ulw:
        return _decision("bypass_owner_learning", "non_ulw_workflow", family, count)
    if named_owner:
        return _decision("bypass_owner_learning", "owner_named_in_request", family, count)
    if multiple_owners:
        return _decision("ask_explicit_owner", "multiple_owners_named", family, count)
    if authority_blocked:
        return _decision("ask_explicit_owner", "authority_requires_choice", family, count)
    if not owner_ready:
        return _decision("ask_explicit_owner", "owner_unready", family, count)
    if not capability_fit:
        return _decision("ask_explicit_owner", "capability_gap", family, count)

    return _decision("ask_explicit_owner", "explicit_choice_required", family, count)


def record_accepted_explicit_choice(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    selected_owner: str,
    occurred_at: str,
    accepted: bool = True,
    explicit: bool = True,
    coding_delivery: bool = True,
    ulw: bool = True,
    named_owner: bool = False,
    multiple_owners: bool = False,
    authority_blocked: bool = False,
    owner_ready: bool = True,
    capability_fit: bool = True,
) -> dict[str, Any]:
    """Record one qualifying accepted explicit handoff without mutating input.

    A changed owner starts a new streak at one and leaves a visible reset
    reason.  Non-qualifying events are exact no-ops; in particular, outcomes,
    model choices, latency, and benchmark data are not parameters and cannot
    influence this transition.
    """
    family = require_opaque_metadata_ref(route_family, field="route_family")
    owner = require_opaque_metadata_ref(selected_owner, field="selected_owner")
    timestamp = _require_timestamp(occurred_at, field="occurred_at")
    safe = _safe_state(state)
    if not _qualifies(
        accepted=accepted,
        explicit=explicit,
        coding_delivery=coding_delivery,
        ulw=ulw,
        named_owner=named_owner,
        multiple_owners=multiple_owners,
        authority_blocked=authority_blocked,
        owner_ready=owner_ready,
        capability_fit=capability_fit,
    ):
        return safe

    updated = deepcopy(safe)
    previous = updated["routes"].get(family)
    changed = previous is not None and previous["selected_owner"] != owner
    if previous is None or changed or not previous["selected_owner"]:
        count = 1
        first_choice_at = timestamp
        learned_at = ""
    else:
        count = int(previous["consecutive_accepted_explicit_choices"]) + 1
        first_choice_at = str(previous["first_choice_at"])
        learned_at = str(previous["learned_at"])
    if count >= OWNER_PREFERENCE_LEARNING_THRESHOLD and not learned_at:
        learned_at = timestamp

    updated["routes"][family] = {
        "route_family": family,
        "selected_owner": owner,
        "consecutive_accepted_explicit_choices": count,
        "first_choice_at": first_choice_at,
        "last_choice_at": timestamp,
        "learned_at": learned_at,
        "reset_at": timestamp if changed else str(previous["reset_at"]) if previous else "",
        "reset_reason": (
            "explicit_owner_changed" if changed else str(previous["reset_reason"]) if previous else ""
        ),
        "provenance": "accepted_explicit_choice",
        "naming_cue": "",
    }
    updated["updated_at"] = timestamp
    _raise_if_invalid(updated)
    return updated


def record_in_message_explicit_naming(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    selected_owner: str,
    naming_cue: str,
    occurred_at: str,
) -> dict[str, Any]:
    """Record that the user named the coding owner in their own message.

    Naming is choosing: a message that names a coding CLI is an explicit
    in-message choice, and this writer records it as such at resolution time,
    preserving the routing cue (for example ``named_executor:codex``) as the
    diagnostic — never the message prose, which this store must not hold.

    Unlike `record_accepted_explicit_choice`, an in-message naming never
    advances the learning streak: the learned visible default remains earned
    exclusively by accepted answers to the coding-owner question. A naming for
    an unrecorded or changed owner starts the route at a streak of one; a
    naming for the already-recorded owner refreshes the timestamp and the cue
    without touching the streak.
    """
    family = require_opaque_metadata_ref(route_family, field="route_family")
    owner = require_opaque_metadata_ref(selected_owner, field="selected_owner")
    cue = require_opaque_metadata_ref(naming_cue, field="naming_cue")
    timestamp = _require_timestamp(occurred_at, field="occurred_at")
    updated = deepcopy(_safe_state(state))
    previous = updated["routes"].get(family)
    changed = previous is not None and previous["selected_owner"] != owner
    if previous is None or changed or not previous["selected_owner"]:
        route = {
            "route_family": family,
            "selected_owner": owner,
            "consecutive_accepted_explicit_choices": 1,
            "first_choice_at": timestamp,
            "last_choice_at": timestamp,
            "learned_at": "",
            "reset_at": timestamp if changed else "",
            "reset_reason": "explicit_owner_changed" if changed else "",
            "provenance": "in_message_naming",
            "naming_cue": cue,
        }
    else:
        route = dict(previous)
        route["last_choice_at"] = timestamp
        route["provenance"] = "in_message_naming"
        route["naming_cue"] = cue
    updated["routes"][family] = route
    updated["updated_at"] = timestamp
    _raise_if_invalid(updated)
    return updated


def explicit_choice_provenance(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
) -> str:
    """Return the explicit-choice provenance recorded for one route family.

    Empty string means no explicit-choice writer recorded an owner for the
    family — including missing, malformed, reset, or raw-written state — and
    therefore no external coding CLI may appear as the selected owner.
    """
    safe = _safe_state(state)
    route = safe["routes"].get(route_family)
    if not route or not route.get("selected_owner"):
        return ""
    provenance = str(route.get("provenance", "") or "")
    if provenance in OWNER_PREFERENCE_EXPLICIT_CHOICE_PROVENANCES:
        return provenance
    return ""


def reset_owner_preference(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    reason: str,
    occurred_at: str,
) -> dict[str, Any]:
    """Explicitly clear one route-family preference and retain reset metadata."""
    family = require_opaque_metadata_ref(route_family, field="route_family")
    reset_reason = require_opaque_metadata_ref(reason, field="reset reason")
    timestamp = _require_timestamp(occurred_at, field="occurred_at")
    updated = deepcopy(_safe_state(state))
    updated["routes"][family] = {
        "route_family": family,
        "selected_owner": "",
        "consecutive_accepted_explicit_choices": 0,
        "first_choice_at": "",
        "last_choice_at": "",
        "learned_at": "",
        "reset_at": timestamp,
        "reset_reason": reset_reason,
        "provenance": "",
        "naming_cue": "",
    }
    updated["updated_at"] = timestamp
    _raise_if_invalid(updated)
    return updated


def owner_preference_path(paths: OmhPaths) -> Path:
    """Return the dedicated artifact path, separate from setup-profile state."""
    return paths.omh_home.joinpath(*OWNER_PREFERENCE_PATH_SEGMENTS)


def read_owner_preference(paths: OmhPaths) -> dict[str, Any]:
    """Read valid learned state; missing, unreadable, or corrupt state is empty."""
    state, error = read_json_object_result(owner_preference_path(paths))
    if error or state is None or validate_owner_preference(state):
        return empty_owner_preference_state()
    return state


def write_owner_preference(paths: OmhPaths, state: Mapping[str, Any]) -> Path:
    """Validate and atomically write the private preference artifact."""
    _raise_if_invalid(state)
    path = owner_preference_path(paths)
    atomic_write_json(path, dict(state), private=True)
    return path


def _decision(action: str, reason_code: str, route_family: str, count: int) -> OwnerPreferenceDecision:
    reasons = {
        "non_coding_workflow": "Owner learning does not apply to a non-coding workflow.",
        "non_ulw_workflow": "Owner learning does not apply outside an ULW workflow.",
        "owner_named_in_request": "The request already names an owner, so learned state is bypassed.",
        "multiple_owners_named": "Multiple named owners require a fresh explicit choice.",
        "authority_requires_choice": "The authority boundary requires a fresh explicit choice.",
        "owner_unready": "The learned owner is not ready, so the owner choice is reopened.",
        "capability_gap": "A required capability is not met, so the owner choice is reopened.",
        "explicit_choice_required": (
            "No owner is named in this request, and an earlier choice never counts for it; ask for an explicit choice."
        ),
    }
    return OwnerPreferenceDecision(
        action=action,
        reason_code=reason_code,
        reason=reasons[reason_code],
        route_family=route_family,
        selected_owner="",
        evidence_count=count,
        override_available=False,
    )


def _qualifies(**flags: bool) -> bool:
    return (
        flags["accepted"]
        and flags["explicit"]
        and flags["coding_delivery"]
        and flags["ulw"]
        and not flags["named_owner"]
        and not flags["multiple_owners"]
        and not flags["authority_blocked"]
        and flags["owner_ready"]
        and flags["capability_fit"]
    )


def _safe_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping) or validate_owner_preference(state):
        return empty_owner_preference_state()
    return deepcopy(dict(state))


def _require_timestamp(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _valid_timestamp(value):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    return value


def _raise_if_invalid(state: Mapping[str, Any]) -> None:
    errors = validate_owner_preference(state)
    if errors:
        raise ValueError("; ".join(errors))
