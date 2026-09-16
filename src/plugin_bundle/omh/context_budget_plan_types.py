"""JSON contracts shared by route-bound plan writers and standalone readers."""
from __future__ import annotations

from typing import Final, Literal, TypedDict

EvidenceClass = Literal["observed", "assumed", "unknown"]
Action = Literal["continue", "checkpoint_required", "overflow_recovery_required", "capacity_unknown_hold", "rebind_loop_hold"]
CAPACITY_FIELDS: Final = (
    "context_window_tokens", "max_output_tokens", "compaction_reserve_tokens", "retained_history_tokens",
)
Evidence = TypedDict("Evidence", {"value": int | None, "class": EvidenceClass, "source": str, "observed_at": str})
Budget = TypedDict("Budget", {"value": int | None, "class": EvidenceClass})


class RouteIdentity(TypedDict):
    executor_profile: str
    provider: str | None
    wire_model: str
    contract_model_id: str
    model_family: str
    catalog_kind: str
    catalog_fingerprint: None


class Derivation(TypedDict):
    operation: str
    operands: dict[str, Evidence]


class RouteCapacity(TypedDict):
    schema_version: str
    route_identity: RouteIdentity
    route_identity_digest: str
    capacity: dict[str, Evidence]
    effective_capacity_digest: str
    usable_budget_tokens: Budget
    derivation: Derivation


# The item classes a must-keep pack may count. The vocabulary is closed because
# a digest comparison can only name a class it was told about: the point of
# recording them is that "the pack changed" becomes "the prohibition class lost
# an item". The seven are the loss categories the workflow's own safety rule
# forbids -- requirements, paths, PR state, verification gaps, explicit
# constraints -- plus the decisions and open questions a resumed session cannot
# reconstruct from the code.
MUST_KEEP_ITEM_CLASSES: Final = (
    "prohibitions", "decisions", "open_questions", "requirements", "paths", "pr_state", "verification_gaps",
)
# Refs are a bounded sample, not an inventory. `read_plan` caps a stored plan at
# 32768 bytes, and seven classes of unbounded refs would reach that before the
# capacity record is written.
MUST_KEEP_REFS_PER_CLASS: Final = 8
MustKeepClass = TypedDict("MustKeepClass", {"count": int, "refs": list[str]})


class MustKeep(TypedDict):
    digest: str
    estimated_tokens_total: int
    # `None` means the pack never recorded classes -- a plan written before this
    # field existed, or a writer that declined to. It is not an empty pack: an
    # empty dict says "counted, none present", and a comparison must report the
    # difference rather than treat silence as zero.
    item_classes: dict[str, MustKeepClass] | None


class MustKeepClassDelta(TypedDict):
    item_class: str
    previous_count: int
    current_count: int
    dropped_refs: list[str]


class MustKeepDelta(TypedDict):
    schema_version: str
    digest_matches: bool
    comparison: Literal["compared", "unavailable"]
    unavailable_reason: str
    missing_classes: list[str]
    reduced_classes: list[MustKeepClassDelta]
    claim_boundary: str


class Invalidation(TypedDict):
    reason: str
    action: Action


class ObservationClocks(TypedDict):
    local_estimate: None
    provider_usage: None
    compaction: None
    billing: None


class Observations(TypedDict):
    provider_usage_observed: Literal["not_observed"]
    compaction_observed: Literal["not_observed"]
    billing_observed: Literal["not_observed"]
    local_token_estimate: Budget
    observation_clocks: ObservationClocks


class Plan(Observations):
    schema_version: str
    session_ref: str
    plan_id: str
    superseded_plan_id: str | None
    route_capacity: RouteCapacity
    must_keep_pack: MustKeep
    stale: bool
    invalidation: Invalidation
    rebind_count: int
    route_history: list[str]
    active_budget_source: RouteCapacity


class PreparedPlan(Plan):
    # The comparison against the pack this preparation replaced. It describes
    # one call, so it is returned and never written into the stored plan.
    must_keep_delta: MustKeepDelta


class Recovery(TypedDict):
    max_checkpoint_attempts: int
    completion: Literal["not_observed"]
    resolution: str


class HostRoute(TypedDict):
    wire_model_matches: bool
    provider: None
    provider_observation: Literal["unknown"]


class BudgetContext(Observations):
    schema_version: str
    plan_id: str | None
    must_keep_pack: MustKeep | None
    stale: bool
    invalidation: Invalidation
    usable_budget_tokens: Budget
    active_budget_source: RouteCapacity | None
    host_route: HostRoute
    recovery: Recovery
    claim_boundary: str


class BudgetPlanError(ValueError):
    """A bounded reason code for invalid local plan metadata."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
