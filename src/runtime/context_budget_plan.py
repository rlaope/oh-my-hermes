"""Explicit control-plane publication of session-bound context plans."""
from __future__ import annotations

import json

from ..coding.model_contracts import contract_model_id
from ..coding.model_routing import model_family, resolve_model_route
from ..plugin_bundle.omh.active_workflow_context_state import session_fingerprint
from ..plugin_bundle.omh.context_budget_plan import evaluate_capacity
from ..plugin_bundle.omh.context_budget_plan_capacity import (
    build_capacity_record, digest_json, metadata_ref, must_keep_delta, observations,
)
from ..plugin_bundle.omh.context_budget_plan_store import context_budget_plan_path, read_plan
from ..plugin_bundle.omh.context_budget_plan_types import (
    BudgetPlanError, Evidence, Invalidation, MustKeep, Plan, PreparedPlan, RouteIdentity,
)
from ..system.local_store import atomic_write_json
from ..system.paths import OmhPaths


def build_route_identity(executor_profile: str, provider: str, model: str) -> RouteIdentity:
    """Use the pure resolver without inferring provider from a model string.

    Explicit passthrough consults no injected catalog, so fingerprint is null.
    Wire spelling remains exact, including provider-qualified model strings.
    """
    metadata_ref(executor_profile)
    metadata_ref(provider, optional=True)
    metadata_ref(model)
    route = resolve_model_route(executor_profile, requested_model=model)
    return {
        "executor_profile": executor_profile, "provider": provider or None, "wire_model": model,
        "contract_model_id": contract_model_id(model), "model_family": model_family(model),
        "catalog_kind": str(route["catalog_kind"]), "catalog_fingerprint": None,
    }


def prepare_context_budget_plan(paths: OmhPaths, *, session_ref: str, identity: RouteIdentity,
                                capacity: dict[str, Evidence], must_keep: MustKeep) -> PreparedPlan:
    """Explicit preparation is the only operation that starts a new recovery lineage.

    This publishes operator-reviewed metadata, not a receipt that the operator
    actually checkpointed, compacted, or delivered this pack to a model.

    Re-preparing over an existing session is where a pack is discovered to have
    lost something, so the returned payload carries the item-class delta against
    the pack being replaced. The delta describes this call and is not persisted:
    the stored plan records the pack, and every later read compares against
    whatever the next writer supplies.
    """
    previous, unreadable = _previous_pack(paths, session_ref)
    record = build_capacity_record(identity, capacity)
    invalidation = evaluate_capacity(None, record, must_keep["estimated_tokens_total"])
    plan: Plan = {
        "schema_version": "context_budget_plan/v1", "session_ref": session_fingerprint(session_ref),
        "plan_id": digest_json(json.dumps([session_fingerprint(session_ref), record, must_keep], sort_keys=True)),
        "superseded_plan_id": None, "route_capacity": record, "must_keep_pack": must_keep,
        "stale": invalidation["action"] != "continue", "invalidation": invalidation,
        "rebind_count": 0, "route_history": [], "active_budget_source": record, **observations(must_keep),
    }
    atomic_write_json(context_budget_plan_path(str(paths.omh_home), session_ref), dict(plan), private=True)
    delta = must_keep_delta(previous, must_keep, previous_unreadable=unreadable)
    return {**plan, "must_keep_delta": delta}


def _previous_pack(paths: OmhPaths, session_ref: str) -> tuple[MustKeep | None, bool]:
    """An unreadable prior plan is no comparison basis, never a clean slate.

    `read_plan` raises on corrupt or foreign data, and preparation must still
    publish. Returning a bare `None` for both cases would make the delta read
    `no_previous_pack`, which asserts there was nothing there to lose; the flag
    keeps "no plan yet" and "a plan that would not parse" distinguishable.
    """
    try:
        plan = read_plan(str(paths.omh_home), session_ref)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None, True
    return (plan["must_keep_pack"] if plan else None), False


def rebind_context_budget_plan(paths: OmhPaths, *, session_ref: str, identity: RouteIdentity,
                               capacity: dict[str, Evidence]) -> Plan:
    """Rebind once per changed effective policy; an equal refresh clears no debt."""
    previous = read_plan(str(paths.omh_home), session_ref)
    if previous is None:
        raise BudgetPlanError("plan_not_found")
    record = build_capacity_record(identity, capacity)
    changed = previous["route_capacity"]["effective_capacity_digest"] != record["effective_capacity_digest"]
    invalidation: Invalidation = evaluate_capacity(previous, record, previous["must_keep_pack"]["estimated_tokens_total"])
    count = min(9, previous["rebind_count"] + int(changed))
    if count >= 9:
        invalidation = {"reason": "rebind_limit", "action": "rebind_loop_hold"}
    history = previous["route_history"]
    if record["route_identity_digest"] != previous["route_capacity"]["route_identity_digest"]:
        history = [*history, previous["route_capacity"]["route_identity_digest"]][-8:]
    plan: Plan = {
        **previous, "route_capacity": record, "active_budget_source": record,
        "plan_id": digest_json(json.dumps([previous["plan_id"], record["effective_capacity_digest"]])) if changed else previous["plan_id"],
        "superseded_plan_id": previous["plan_id"] if changed else previous["superseded_plan_id"],
        "stale": invalidation["action"] != "continue", "invalidation": invalidation,
        "rebind_count": count, "route_history": history,
    }
    atomic_write_json(context_budget_plan_path(str(paths.omh_home), session_ref), dict(plan), private=True)
    return plan


def context_budget_plan_status(paths: OmhPaths, *, session_ref: str) -> Plan:
    plan = read_plan(str(paths.omh_home), session_ref)
    if plan is None:
        raise BudgetPlanError("plan_not_found")
    return plan
