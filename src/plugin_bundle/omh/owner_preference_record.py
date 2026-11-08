"""`coding_owner_preference/v1`: the closed schema of the explicit coding-owner choice, and who it names.

The one validator of the record. The router's reader and writer
(`omh.routing.owner_preference`) import it from here: a missing, malformed,
reset or hand-written record names no owner, and no external coding CLI may
be selected from it. `omh_dag` reads no record: a dag-ulw run's owners are
the ones named in the request that defined it (`named_owner_choice`).

Pure and stdlib only, and it imports nothing from `omh`: Hermes loads this
directory with its own interpreter (#1623). The opaque-reference check is
`omh.system.metadata_safety.require_opaque_metadata_ref`'s, copied because
the bundle cannot import it; `tests/test_dag_tool.py` holds the two copies'
patterns equal.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any, Final
from .iso_datetime import strict_fromisoformat
from .pi_family_names import LEGACY_RUNTIME_RECORD_VALUES

OWNER_PREFERENCE_SCHEMA_VERSION: Final = "coding_owner_preference/v1"
OWNER_PREFERENCE_RECORD_TYPE: Final = "coding_owner_preference"
OWNER_PREFERENCE_LEARNING_THRESHOLD: Final = 3
OWNER_PREFERENCE_EXCLUDED_SIGNALS: Final = (
    "performance",
    "failure",
    "benchmark",
    "latency",
    "model_choice",
)
OWNER_PREFERENCE_PATH_SEGMENTS: Final = ("routing", "owner-preference.json")
# The two explicit-choice writers. An external coding CLI may appear as the
# selected owner only when route state carries one of these provenances:
# the user answered the coding-owner question (`record_accepted_explicit_choice`)
# or named the CLI in their own words (`record_in_message_explicit_naming`).
# The route families keep only those two router writers. A dag-ulw run reads
# none of them: its owners are the ones named in the request that defined it
# (`named_owner_choice`).
# Deriving an external owner from a message that does NOT name that CLI —
# topic, language, history, or heuristics — stays forbidden.
OWNER_PREFERENCE_EXPLICIT_CHOICE_PROVENANCES: Final = (
    "accepted_explicit_choice",
    "in_message_naming",
)

STATE_KEYS: Final = frozenset({"schema_version", "record_type", "privacy", "routes", "updated_at"})
PRIVACY_KEYS: Final = frozenset({"mode", "learning_source", "excluded_signals"})
ROUTE_KEYS: Final = frozenset({
    "route_family",
    "selected_owner",
    "consecutive_accepted_explicit_choices",
    "first_choice_at",
    "last_choice_at",
    "learned_at",
    "reset_at",
    "reset_reason",
    "provenance",
    "naming_cue",
})

# `omh.system.metadata_safety`'s opaque-reference check, held equal by a test.
OPAQUE_REFERENCE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
SENSITIVE_MARKERS: Final = (
    "secret",
    "token",
    "password",
    "private-key",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "bearer",
)
SECRET_VALUE_PATTERNS: Final = (
    re.compile(r"(?:^|[^a-z0-9])(?:sk|pk|rk|xox[a-z]?)[_-][a-z0-9_-]{8,}", re.IGNORECASE),
    re.compile(r"(?:^|[^a-z0-9])(?:gh[oprs]|github_pat|npm|whsec|glpat)[_-][a-z0-9_-]{16,}", re.IGNORECASE),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
)


def opaque_ref_ok(value: object) -> bool:
    """Whether ``value`` is a safe opaque metadata reference: short, plain, and not named or shaped like a secret."""
    if not isinstance(value, str) or not OPAQUE_REFERENCE.fullmatch(value):
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return False
    return not any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)


def valid_timestamp(value: str) -> bool:
    try:
        parsed = strict_fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_owner_preference(state: Mapping[str, Any]) -> list[str]:
    """Validate the closed owner-preference schema without raising."""
    errors: list[str] = []
    if set(state) != STATE_KEYS:
        errors.append("owner preference must contain exactly the schema fields")
    if state.get("schema_version") != OWNER_PREFERENCE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {OWNER_PREFERENCE_SCHEMA_VERSION}")
    if state.get("record_type") != OWNER_PREFERENCE_RECORD_TYPE:
        errors.append(f"record_type must be {OWNER_PREFERENCE_RECORD_TYPE}")

    privacy = state.get("privacy")
    if not isinstance(privacy, Mapping) or set(privacy) != PRIVACY_KEYS:
        errors.append("privacy must contain exactly mode, learning_source, and excluded_signals")
    elif (
        privacy.get("mode") != "metadata_only"
        or privacy.get("learning_source") != "accepted_explicit_owner_choice"
        or privacy.get("excluded_signals") != list(OWNER_PREFERENCE_EXCLUDED_SIGNALS)
    ):
        errors.append("privacy must preserve the explicit-choice-only metadata boundary")

    updated_at = state.get("updated_at")
    if not isinstance(updated_at, str) or (updated_at and not valid_timestamp(updated_at)):
        errors.append("updated_at must be empty or an ISO-8601 timestamp")

    routes = state.get("routes")
    if not isinstance(routes, Mapping):
        errors.append("routes must be a route-family mapping")
        return errors
    for key, route in routes.items():
        errors.extend(route_errors(key, route))
    return errors


def route_errors(key: object, route: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(key, str):
        return ["route-family keys must be strings"]
    if not opaque_ref_ok(key):
        return ["route-family key must be a safe opaque metadata reference"]
    family = key
    if not isinstance(route, Mapping) or set(route) != ROUTE_KEYS:
        return [f"route {family} must contain exactly the route preference fields"]
    if route.get("route_family") != family:
        errors.append(f"route {family} must repeat its route-family key")

    owner = route.get("selected_owner")
    if not isinstance(owner, str):
        errors.append(f"route {family} selected_owner must be a string")
    elif owner and not opaque_ref_ok(owner):
        errors.append(f"route {family} selected_owner must be a safe opaque metadata reference")
    count = route.get("consecutive_accepted_explicit_choices")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append(f"route {family} consecutive choice count must be a nonnegative integer")
        count = -1
    if (count == 0) != (owner == ""):
        errors.append(f"route {family} owner must be empty exactly when its count is zero")

    for field in ("first_choice_at", "last_choice_at", "learned_at", "reset_at"):
        value = route.get(field)
        if not isinstance(value, str) or (value and not valid_timestamp(value)):
            errors.append(f"route {family} {field} must be empty or an ISO-8601 timestamp")
    if count > 0 and (not route.get("first_choice_at") or not route.get("last_choice_at")):
        errors.append(f"route {family} a nonempty streak requires first and last timestamps")
    if count >= OWNER_PREFERENCE_LEARNING_THRESHOLD and not route.get("learned_at"):
        errors.append(f"route {family} a learned streak requires learned_at")
    if 0 <= count < OWNER_PREFERENCE_LEARNING_THRESHOLD and route.get("learned_at"):
        errors.append(f"route {family} an unlearned streak cannot have learned_at")

    reason = route.get("reset_reason")
    if not isinstance(reason, str):
        errors.append(f"route {family} reset_reason must be a string")
    elif reason and not opaque_ref_ok(reason):
        errors.append(f"route {family} reset_reason must be a safe opaque metadata reference")
    if bool(reason) != bool(route.get("reset_at")):
        errors.append(f"route {family} reset_reason and reset_at must appear together")

    provenance = route.get("provenance")
    allowed_provenances = ("", *OWNER_PREFERENCE_EXPLICIT_CHOICE_PROVENANCES)
    if not isinstance(provenance, str) or provenance not in allowed_provenances:
        errors.append(
            f"route {family} provenance must be empty or one of "
            f"{', '.join(OWNER_PREFERENCE_EXPLICIT_CHOICE_PROVENANCES)}"
        )
        provenance = ""
    cue = route.get("naming_cue")
    if not isinstance(cue, str):
        errors.append(f"route {family} naming_cue must be a string")
    elif cue:
        if not opaque_ref_ok(cue):
            errors.append(f"route {family} naming_cue must be a safe opaque metadata reference")
        if provenance != "in_message_naming":
            errors.append(f"route {family} naming_cue requires in_message_naming provenance")
    elif provenance == "in_message_naming":
        errors.append(f"route {family} in_message_naming provenance requires a naming_cue")
    return errors


SETUP_PROFILE_FILE: Final = "setup-profile.json"
# The executor profile ids a setup profile may name, copied from `omh.coding_delegation.CODING_EXECUTOR_TARGETS`
# (the bundle cannot import it); `tests/test_profile_default_owner.py` holds the two equal. "choose" is unset.
SETUP_PROFILE_EXECUTORS: Final = frozenset(
    {"codex", "claude-code", "omx-runtime", "pi-family-runtime", "omc-runtime", "generic", "hermes"}
)


def setup_profile_owner(omh_home: str | Path | None) -> str:
    """The default coding owner `<omh_home>/setup-profile.json` names, or "", read as the wrapper reads it.

    Read per call, so a profile edit counts on the next turn. An id an older
    release stored is mapped to the current one (`LEGACY_RUNTIME_RECORD_VALUES`);
    a missing, unreadable or malformed profile, "choose", or a value that is not
    an executor profile id names no owner, and the hint then asks, as the
    wrapper does.
    """
    if omh_home is None or not str(omh_home):
        return ""
    try:
        profile = json.loads((Path(omh_home) / SETUP_PROFILE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return ""
    owner = profile.get("default_executor") if isinstance(profile, dict) else None
    owner = owner.strip() if isinstance(owner, str) else ""
    owner = LEGACY_RUNTIME_RECORD_VALUES.get(owner, owner)
    return owner if owner in SETUP_PROFILE_EXECUTORS else ""
