"""Stable facade for pure, approval-gated paired-run dispatch planning.

The facade intentionally has no runner.  It consumes only an existing
``paired_run_decision`` (v2, or v1 history) through its established parser and returns prepared
metadata for a separately approved execution surface.
"""

from __future__ import annotations

from ..quality.paired_run_decision import parse_paired_run_decision
from .paired_run_dispatch_model import (
    CLAIM_BOUNDARY,
    ApprovalState,
    ArmDispatchTarget,
    CostTimeBound,
    DispatchBudgets,
    NamedConcurrencyBudget,
    PairedRunDispatchCell,
    PairedRunDispatchConfig,
    PairedRunDispatchPlan,
    PairedRunDispatchPlanError,
    SharedResourceMode,
    TerminalState,
)
from .paired_run_dispatch_planner import build_cells, record_terminal_state
from .paired_run_dispatch_validation import validate_dispatch_inputs


__all__ = [
    "CLAIM_BOUNDARY",
    "ApprovalState",
    "ArmDispatchTarget",
    "CostTimeBound",
    "DispatchBudgets",
    "NamedConcurrencyBudget",
    "PairedRunDispatchCell",
    "PairedRunDispatchConfig",
    "PairedRunDispatchPlan",
    "PairedRunDispatchPlanError",
    "SharedResourceMode",
    "TerminalState",
    "plan_paired_run_dispatch",
    "record_terminal_state",
]


def plan_paired_run_dispatch(
    decision_document: str,
    config: PairedRunDispatchConfig,
) -> PairedRunDispatchPlan:
    """Build an inert deterministic plan from the validated decision contract."""
    decision = parse_paired_run_decision(decision_document)
    targets = validate_dispatch_inputs(decision, config)
    return PairedRunDispatchPlan(
        decision.decision_id,
        config.approval,
        config.dry_run,
        build_cells(decision, config.budgets, targets),
    )
