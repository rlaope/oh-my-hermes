from __future__ import annotations

import re
import shlex

from .executors import EXECUTOR_PROFILES, HERMES_CODING_TEAM_STATUS_LADDER


FANOUT_CONTRACT_SCHEMA_VERSION = "fanout_contract/v2"
LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION = "fanout_contract/v1"
FANOUT_CONTRACT_PROVENANCE_SCHEMA_VERSION = "fanout_contract_provenance/v1"
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

# The key set a `fanout_contract/v1` freeze carries. `safety_profile_revision`
# and `spawn_plan` are optional and additive: an install without the preflight
# evaluator omits the first, and a split that needed no justification omits the
# second. Everything else is always present. Declared here rather than inlined
# in a test so the contract's shape lives beside its schema version.
FANOUT_CONTRACT_KEYS = (
    "board_projection",
    "claim_boundary",
    "fanout_id",
    "goal",
    "merge_plan",
    "observed_evidence_required",
    "schema_version",
    "source",
    "source_metadata",
    "status",
    "units",
)
FANOUT_CONTRACT_OPTIONAL_KEYS = ("safety_profile_revision", "spawn_plan")

FANOUT_SPAWN_PLAN_SCHEMA_VERSION = "fanout_spawn_plan/v1"
# Up to four units a split is small enough to read at a glance. Past that the
# contract stops recording an obvious decomposition and starts recording a
# guess, so the operator has to say why out loud. The threshold is locked
# rather than configurable on purpose: a threshold that can be raised is a
# threshold that gets raised instead of answered.
FANOUT_SPAWN_PLAN_THRESHOLD = 4
# Four questions, all prose. Gajae-Code's receipt carries a fifth,
# `maxInlineTokens`, because its parent agent enforces an inline-output budget
# on the child. OMH has no such consumer — the units are foreign CLI processes
# whose output it does not bound — so requiring the operator to invent a number
# nothing reads would be a mandatory unbounded field with no reader. Left out
# until something needs it.
FANOUT_SPAWN_PLAN_FIELDS = (
    "why_parallel",
    "why_not_single_unit",
    "independence",
    "expected_evidence_shape",
)
# Bounded for the reason every operator-typed contract string is bounded here:
# a field with no ceiling is a field that eventually carries a pasted
# transcript. One or two sentences is the whole intent.
MAX_SPAWN_PLAN_FIELD_CHARS = 280
FANOUT_SPAWN_PLAN_CLAIM_BOUNDARY = (
    "A spawn plan is the operator's prepared justification for splitting one goal across several units. "
    "It is not evidence that the split is correct, that the units are independent, that the named evidence "
    "shape was produced, or that any unit ran."
)


# Optional per-unit executable verification. A unit may carry command strings
# the dispatcher runs itself under `--run-verification`; the prose
# `integration_checks` stay beside them, unchanged. Bounded like every other
# operator-typed contract string: eight commands is more than one unit boundary
# can justify, and 240 chars is a command line rather than a pasted script.
MAX_UNIT_VERIFICATION_COMMANDS = 8
MAX_UNIT_VERIFICATION_COMMAND_CHARS = 240
# Named once so the check rows the dispatcher writes, the journal event they
# back, and the docs describing both cannot drift apart.
UNIT_VERIFICATION_OBSERVATION_SOURCE = "dispatch_verification"

# A leading `NAME=VALUE` token: the one shell idiom a verification command may
# use, because the repo's own integration gate is spelled that way.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class FanoutContractError(ValueError):
    """Raised when a proposed fanout unit list cannot be frozen into a contract."""


def verification_command_argv(command: str) -> tuple[dict[str, str], list[str]]:
    """Split one verification command into env overrides and an argv.

    No shell ever runs one of these — the split happens here and the argv is
    executed with `shell=False` — so pipes, redirections, and substitutions are
    ordinary argument text rather than operators. Leading `NAME=VALUE` tokens
    are the single exception, kept because `PYTHONPATH=tests uv run ...` is how
    this repo's own gate commands are written and refusing them would make the
    field unusable for exactly the commands it exists to carry.

    Raises `FanoutContractError` so the freeze path rejects an unrunnable
    command where the operator can still fix it.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise FanoutContractError(f"verification command is not parseable: {exc}") from exc
    env: dict[str, str] = {}
    while tokens and _ENV_ASSIGNMENT_RE.match(tokens[0]):
        name, _, value = tokens.pop(0).partition("=")
        env[name] = value
    if not tokens:
        raise FanoutContractError("verification command must name a program to run")
    return env, tokens
