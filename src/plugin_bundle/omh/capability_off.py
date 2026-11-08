"""Which OMH skills this home turned off, read the way the tools read it.

`omh capability-policy disable <family>` records the family in
`<omh_home>/setup-profile.json` under `capability_policy.disabled_families`.
The memory tool already stops on that field (`memory_admission`); this module
reads the same field so the router, the route hint and the skill-candidate
line stop naming the family's skills too, and so a request for that work is
answered with the family being off and the command that turns it back on,
instead of being routed somewhere else without a word.

Read on every call, never cached: the file is small, it is the same file the
memory path reads per call, and a profile-scoped OMH home is a different file,
so one process serving two homes must not answer one with the other's policy.

A family's members are the `primary_workflows` of its card in the generated
`tools/capability_families.json` sidecar, which `omh docs
capability-families --check` keeps byte-identical to the core projection. The
core skills survive every disable, as `omh capability-policy` says they do, so
they are never in the returned map.

An absent, unreadable or malformed profile reads as nothing turned off: that is
what an install without the policy means, and routing then renders exactly the
bytes it rendered before this filter existed. The memory tool reports an
unreadable profile on its own path.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Final, Mapping

SETUP_PROFILE_NAME: Final = "setup-profile.json"
POLICY_KEY: Final = "capability_policy"
DISABLED_KEY: Final = "disabled_families"
CAPABILITY_OFF_SCHEMA_VERSION: Final = "omh_capability_family_off/v1"
CAPABILITY_OFF_REASON_CODE: Final = "capability_family_disabled"
# Vendored from `omh.skills.catalog.CORE_SKILLS`; the bundle cannot import the
# catalog. `tests/test_capability_family_routing.py` holds the two equal.
CORE_SKILLS: Final = frozenset({"oh-my-hermes", "doctor", "skill", "cancel", "agent-ops-review"})
_SIDECAR: Final = Path(__file__).resolve().parent / "tools" / "capability_families.json"


@lru_cache(maxsize=1)
def _family_cards() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """(id, label, member workflows) per family card; package data, so cached for the process."""
    try:
        payload = json.loads(_SIDECAR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    cards: list[tuple[str, str, tuple[str, ...]]] = []
    for card in payload if isinstance(payload, list) else ():
        if not isinstance(card, dict) or not isinstance(card.get("id"), str):
            continue
        workflows = card.get("primary_workflows")
        cards.append(
            (
                card["id"],
                str(card.get("label") or card["id"]),
                tuple(str(item) for item in workflows) if isinstance(workflows, list) else (),
            )
        )
    return tuple(cards)


def disabled_families_in_profile(profile: Mapping[str, object] | None) -> frozenset[str]:
    """The family ids an already-loaded setup profile turns off, as written; empty when it turns none off."""
    policy = profile.get(POLICY_KEY) if isinstance(profile, Mapping) else None
    if not isinstance(policy, Mapping):
        return frozenset()
    disabled = policy.get(DISABLED_KEY, [])
    if not isinstance(disabled, list):
        return frozenset()
    return frozenset(str(value) for value in disabled)


def disabled_family_ids(omh_home: str | Path | None) -> tuple[str, ...]:
    """The known family ids `<omh_home>/setup-profile.json` turns off, sorted; `()` when none or unreadable."""
    return read_disabled_family_ids(omh_home)[0]


def read_disabled_family_ids(omh_home: str | Path | None) -> tuple[tuple[str, ...], str]:
    """(the family ids turned off, why the profile could not be read or "").

    A missing profile is no policy, not a failure, and gives "". A profile that
    exists but does not parse into an object gives the failure's class name, so
    the turn can say routing went ahead without the policy.
    """
    if omh_home is None or not str(omh_home):
        return (), ""
    try:
        profile = json.loads((Path(omh_home) / SETUP_PROFILE_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return (), ""
    except (OSError, ValueError, RecursionError) as exc:
        return (), type(exc).__name__
    if not isinstance(profile, dict):
        return (), "ValueError"
    disabled = disabled_families_in_profile(profile)
    return tuple(sorted(family_id for family_id, _, _ in _family_cards() if family_id in disabled)), ""


def disabled_skill_families(omh_home: str | Path | None) -> dict[str, str]:
    """Each skill this home turned off, mapped to its family id; `{}` when nothing is off."""
    return skill_families_for(disabled_family_ids(omh_home))


def skill_families_for(family_ids: tuple[str, ...]) -> dict[str, str]:
    """Each member skill of `family_ids` but the core ones, mapped to its family id."""
    disabled = set(family_ids)
    if not disabled:
        return {}
    return {
        workflow: family_id
        for family_id, _, workflows in _family_cards()
        if family_id in disabled
        for workflow in workflows
        if workflow not in CORE_SKILLS
    }


def family_label(family_id: str) -> str:
    return next((label for card_id, label, _ in _family_cards() if card_id == family_id), family_id)


def enable_command(family_id: str) -> str:
    return f"omh capability-policy enable {family_id}"


def capability_off_record(workflow: str, family_id: str) -> dict[str, str]:
    """The machine-readable "this family is off" record a route and a hint carry."""
    return {
        "schema_version": CAPABILITY_OFF_SCHEMA_VERSION,
        "workflow": workflow,
        "family": family_id,
        "family_label": family_label(family_id),
        "enable_command": enable_command(family_id),
    }


def capability_off_sentence(workflow: str, family_id: str) -> str:
    """One sentence for the person: which family is off and how to turn it on."""
    return (
        f"`{workflow}` belongs to the {family_label(family_id)} capability family, which is turned off "
        f"in this OMH home; `{enable_command(family_id)}` turns it back on."
    )


__all__ = [
    "CAPABILITY_OFF_REASON_CODE",
    "CAPABILITY_OFF_SCHEMA_VERSION",
    "CORE_SKILLS",
    "capability_off_record",
    "capability_off_sentence",
    "disabled_families_in_profile",
    "disabled_family_ids",
    "disabled_skill_families",
    "enable_command",
    "family_label",
    "read_disabled_family_ids",
    "skill_families_for",
]
