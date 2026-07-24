from __future__ import annotations

from .executors import EXECUTOR_PROFILES, HERMES_CODING_TEAM_STATUS_LADDER


FANOUT_CONTRACT_SCHEMA_VERSION = "fanout_contract/v1"
FANOUT_ID_PATTERN = r"^fanout-[0-9a-f]{12}$"
FANOUT_UNIT_STATUSES = ("prepared", *HERMES_CODING_TEAM_STATUS_LADDER)
FANOUT_UNIT_OWNERS = EXECUTOR_PROFILES
PREPARED_NOT_OBSERVED = "prepared_not_observed"
FANOUT_CLAIM_BOUNDARY = (
    "A fanout contract freezes a proposed parallel work split into prepared per-unit handoffs and a merge plan. "
    "It is not dispatch, execution, implementation, verification, review, CI, merge-readiness, or merge evidence; "
    "unit status advances only on observed per-unit run records."
)
FANOUT_FINAL_INTEGRATION_GATE = (
    "PYTHONPATH=tests uv run python -m unittest discover -s tests",
    "uv run python -m omh.cli docs workflows --check",
    "uv run python -m omh.cli docs roles --check",
    "uv run python -m omh.cli docs capability-families --check",
    "git diff --check",
)


class FanoutContractError(ValueError):
    """Raised when a proposed fanout unit list cannot be frozen into a contract."""
