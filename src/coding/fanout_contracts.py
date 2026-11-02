from __future__ import annotations

import re
import shlex

# Re-exported (`X as X`): callers import both versions from here.
from ..plugin_bundle.omh.run_records import (
    FANOUT_CONTRACT_PROVENANCE_SCHEMA_VERSION as FANOUT_CONTRACT_PROVENANCE_SCHEMA_VERSION,
    FANOUT_CONTRACT_SCHEMA_VERSION as FANOUT_CONTRACT_SCHEMA_VERSION,
)
from .executors import EXECUTOR_PROFILES, HERMES_CODING_TEAM_STATUS_LADDER


LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION = "fanout_contract/v1"
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

# Optional unit kind. The only declared kind is `reproduction`: a unit whose
# job is to make the reported failure fail on purpose, before anything is
# fixed. A split that declares one is debugging-shaped by that declaration and
# nothing else; the request text is never read to decide it. Such a unit
# carries `reproduction_command`, which the dispatcher runs itself and which
# must EXIT NONZERO to count, and every other unit in the split must reach a
# reproduction unit through `depends_on`, so no edit unit can be admitted
# before the failure it fixes has been observed. Absent everywhere, the
# contract is byte-identical to one frozen before the field existed.
REPRODUCTION_UNIT_KIND = "reproduction"
FANOUT_UNIT_KINDS = (REPRODUCTION_UNIT_KIND,)
FANOUT_REPRODUCTION_SCHEMA_VERSION = "fanout_reproduction/v1"
# The journal receipt that makes an observed reproduction survive a resume: a
# later dispatch skips the already-completed reproduction unit and reads this
# event instead of re-running it.
REPRODUCTION_OBSERVED_EVENT = "reproduction_failure_observed"
# The receipt's closed status vocabulary. Only `failure_reproduced` releases
# the hold; `not_reproduced` means the command ran and exited 0 (the failure
# did not reproduce), and `not_observed` means it never produced an exit code
# the dispatcher saw (not requested, dry run, could not start, timed out).
REPRODUCTION_STATUSES = ("failure_reproduced", "not_reproduced", "not_observed")
FANOUT_REPRODUCTION_CLAIM_BOUNDARY = (
    "A reproduction receipt records only whether the dispatcher itself observed the declared reproduction "
    "command exit nonzero in the reproduction unit's worktree. It is not evidence that the failure is the "
    "reported bug, that any fix is correct, or of verification, review, CI, or merge."
)

# Optional per-check metadata (`verification_checks`): the additive,
# structured sibling of `verification_commands` that lets a unit declare
# tiers, read/write safety, dependency edges, and a narrowed timeout per
# check. Same closed-vocabulary rule as every other contract enum: anything
# outside these tuples is a freeze-time refusal, never a silent default.
VERIFICATION_CHECK_TIERS = ("unit", "integration")
VERIFICATION_CHECK_SAFETIES = ("read_only", "stateful")
VERIFICATION_CHECK_RESOURCE_CLASS_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"
VERIFICATION_CHECK_CLAIM_SCOPES = ("unit_verification", "integrated_verification")
# A check may only narrow the dispatcher's per-command ceiling, never widen
# it: the ceiling exists so one hung command cannot hold a dispatch open.
MAX_UNIT_VERIFICATION_CHECK_TIMEOUT = 600
VERIFICATION_CHECK_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
MAX_UNIT_VERIFICATION_CHECK_ID_CHARS = 40

# Optional per-unit input budget: how much document text a unit may read and
# from which ranges. Bounded like every other operator-typed contract field.
# `tokens` is a sanity window on `chars`, not a tokenizer claim: no tokenizer
# emits more tokens than characters, and none averages more than sixteen
# characters per token on prose, so a pair outside that window is a typo
# rather than a budget.
FANOUT_UNIT_INPUT_BUDGET_SCHEMA_VERSION = "fanout_unit_input_budget/v1"
MAX_UNIT_INPUT_BUDGET_CHARS = 10_000_000
MAX_CHARS_PER_TOKEN = 16
MAX_UNIT_SOURCE_RANGES = 64
MAX_UNIT_SOURCE_RANGE_SOURCE_CHARS = 1_000
MAX_UNIT_SOURCE_RANGE_SPAN_CHARS = 200
MAX_UNIT_SOURCE_RANGE_DIGEST_CHARS = 64
UNIT_SOURCE_RANGE_KEYS = ("source", "span", "offset", "limit", "end_line", "estimated_chars", "digest")
FANOUT_UNIT_INPUT_BUDGET_CLAIM_BOUNDARY = (
    "An input budget is the prepared ceiling on what one unit may read and the ranges it reads from. "
    "It is not evidence that the unit read them, stayed within the budget, or covered the range."
)

# A leading `NAME=VALUE` token: the one shell idiom a verification command may
# use, because the repo's own integration gate is spelled that way.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_VERIFICATION_CHECK_RESOURCE_CLASS_RE = re.compile(VERIFICATION_CHECK_RESOURCE_CLASS_PATTERN)


def is_verification_check_resource_class(value: str) -> bool:
    """Whether one contract resource name is safe to use as a lock key."""
    return _VERIFICATION_CHECK_RESOURCE_CLASS_RE.fullmatch(value) is not None


class FanoutContractError(ValueError):
    """Raised when a proposed fanout unit list cannot be frozen into a contract."""


# Unquoted shell syntax in a command that no shell will ever read. Ordered so
# a two-character operator is named before its one-character prefix.
_UNQUOTED_SHELL_OPERATORS = ("&&", "||", "$(", "|", ";", "&", ">", "<", "`")


def unquoted_shell_operator(command: str) -> str:
    """The first shell operator outside quotes in `command`, or "".

    Quote state is tracked the way POSIX `sh` does: nothing is special inside
    single quotes, a backslash escapes the next character outside them, and
    inside double quotes `$(` and backticks still substitute. `grep -E 'a|b'`
    therefore carries no operator, while `test -f x && grep y x` does.
    """
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            if char == "'":
                quote = ""
            index += 1
            continue
        if char == "\\":
            index += 2
            continue
        if quote == '"':
            if char == '"':
                quote = ""
            elif char == "`" or command.startswith("$(", index):
                return "`" if char == "`" else "$("
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        for operator in _UNQUOTED_SHELL_OPERATORS:
            if command.startswith(operator, index):
                return operator
        index += 1
    return ""


def require_shell_free_command(command: str, *, field: str = "verification command") -> None:
    """Refuse a command the dispatcher would run with `shell=False` that needs a shell.

    The fanout dispatcher runs `verification_commands`, `reproduction_command`
    and `task_linked_test_runner` without a shell, so an unquoted `&&`, `||`,
    `|`, `;`, `&`, `>`, `<`, `$(` or backtick reaches the program as a literal
    argument. `test -f x && grep -q y x` then runs `test` with five arguments
    and exits 2 however correct the work is: a check that can never pass
    (#2460). The refusal names both ways to write the check.

    Separate from `verification_command_argv` on purpose: that parser also
    compiles `handoff_contract` postconditions, which the executor runs itself.
    """
    operator = unquoted_shell_operator(command)
    if not operator:
        return
    wrapped = (
        f'sh -c "{command}"'
        if not any(char in command for char in '"\\$`')
        else f"sh -c {shlex.quote(command)}"
    )
    raise FanoutContractError(
        f"{field} uses the shell operator {operator!r} outside quotes, but the dispatcher runs it "
        "without a shell, so the operator would reach the program as a literal argument and the check "
        "could never pass; declare each step as its own command, or wrap it in a shell explicitly: "
        f"{wrapped}"
    )


def verification_command_argv(command: str) -> tuple[dict[str, str], list[str]]:
    """Split one verification command into env overrides and an argv.

    No shell ever runs one of these — the split happens here and the argv is
    executed with `shell=False` — so pipes, redirections, and substitutions are
    ordinary argument text rather than operators. Leading `NAME=VALUE` tokens
    are the single exception, kept because `PYTHONPATH=tests uv run ...` is how
    this repo's own gate commands are written and refusing them would make the
    field unusable for exactly the commands it exists to carry. The fanout
    freeze path refuses such operators first, with `require_shell_free_command`.

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
