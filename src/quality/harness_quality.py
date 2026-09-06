from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from ..coding.skill_load_observation import (
    skill_load_observation_is_fresh,
    validate_skill_load_observation,
)


HARNESS_QUALITY_SCHEMA_VERSION = "harness_quality/v1"
HARNESS_QUALITY_KEYS = (
    "schema_version",
    "harness",
    "quality_tier",
    "quality_bar",
    "evidence_ladder",
    "wrapper_actions",
    "overclaim_guards",
)
HARNESS_PROGRESS_SCHEMA_VERSION = "harness_progress/v1"
# `cancelled` is a member so a stopped step cannot be reported as `blocked`.
# The two ask for different things -- a blocked step is waiting on something,
# a cancelled one is over -- and it is not `complete` or `not_required` either,
# so it counts as unfinished in `build_harness_progress` exactly as `blocked`
# does. `_progress_state` folds anything outside this tuple to `pending`, which
# is why a state has to be admitted here before a step can report it.
HARNESS_PROGRESS_STATES = ("pending", "complete", "blocked", "cancelled", "not_required")


def build_harness_quality_contract(
    *,
    harness: str,
    quality_tier: str,
    quality_bar: Iterable[str],
    evidence_ladder: Iterable[str],
    wrapper_actions: Iterable[str],
    overclaim_guards: Iterable[str],
) -> dict[str, object]:
    return {
        "schema_version": HARNESS_QUALITY_SCHEMA_VERSION,
        "harness": harness,
        "quality_tier": quality_tier,
        "quality_bar": list(quality_bar),
        "evidence_ladder": list(evidence_ladder),
        "wrapper_actions": list(wrapper_actions),
        "overclaim_guards": list(overclaim_guards),
    }


def unknown_harness_quality_contract(name: str) -> dict[str, object]:
    return build_harness_quality_contract(
        harness=name,
        quality_tier="unknown",
        quality_bar=("Treat the harness as unrecognized and ask for explicit operator review before dispatch.",),
        evidence_ladder=("harness_unrecognized", "operator_review_required"),
        wrapper_actions=("show_status",),
        overclaim_guards=("Unknown harness; do not infer runtime capability.",),
    )


def with_wrapper_actions(contract: dict[str, object], allowed_actions: Iterable[str]) -> dict[str, object]:
    allowed = tuple(allowed_actions)
    existing = contract.get("wrapper_actions", [])
    existing_actions = tuple(action for action in existing if isinstance(action, str)) if isinstance(existing, list) else ()
    actions = [action for action in existing_actions if action in allowed]
    if not actions:
        actions = ["show_status"]
    adjusted = dict(contract)
    adjusted["wrapper_actions"] = actions
    return adjusted


def build_harness_progress(contract: dict[str, object], step_states: dict[str, str]) -> dict[str, object]:
    ladder = contract.get("evidence_ladder", [])
    ladder_steps = [step for step in ladder if isinstance(step, str) and step]
    steps = [
        {
            "id": step,
            "state": _progress_state(step_states.get(step, "pending")),
        }
        for step in ladder_steps
    ]
    completed = sum(1 for step in steps if step["state"] in {"complete", "not_required"})
    next_step = next((str(step["id"]) for step in steps if step["state"] in {"blocked", "cancelled", "pending"}), "")
    return {
        "schema_version": HARNESS_PROGRESS_SCHEMA_VERSION,
        "harness": contract.get("harness", "unknown"),
        "quality_tier": contract.get("quality_tier", "unknown"),
        "steps": steps,
        "completed": completed,
        "total": len(steps),
        "complete": bool(steps) and completed == len(steps),
        "next_step": next_step,
    }


def skill_load_evidence_state(
    observation: Mapping[str, object], *, now: datetime | None = None
) -> str:
    """Consume the probe without promoting unsupported, errors, or stale data."""
    if validate_skill_load_observation(observation):
        return "invalid"
    if not skill_load_observation_is_fresh(observation, now=now):
        return "stale"
    status = observation.get("probe_status")
    if status != "observed":
        return str(status)
    return str(observation.get("load_state"))


def _progress_state(value: str) -> str:
    return value if value in HARNESS_PROGRESS_STATES else "pending"
