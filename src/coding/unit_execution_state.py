"""Execution states of one dispatched unit, kept apart from process liveness.

A unit's process being alive says nothing about whether its work is moving.
The 2026-09-11 incident had a worker alive for 36 minutes, retrying the same
git workaround, while the supervisor read "PID alive" as progress. These
states name what OMH has actually observed about the WORK, so that every
surface (inflight markers, status board, run summary, reminders) says the
same thing and none of them renders "alive" as "progressing".
"""

from __future__ import annotations

UNIT_EXECUTION_STATE_SCHEMA_VERSION = "unit_execution_state/v1"

# The work is producing new evidence: output growing, tests starting and
# ending, result records appearing. Only this state means "progressing".
UNIT_STATE_RUNNING = "running"
# The worker asked a question or is waiting on a prompt nobody will answer.
UNIT_STATE_AWAITING_INPUT = "awaiting_input"
# A permission or sandbox denial stopped the work (file write, git index,
# network where forbidden). Retrying under the same permissions cannot clear it.
UNIT_STATE_PERMISSION_BLOCKED = "permission_blocked"
# The provider refused for account reasons: session or usage limit, quota.
UNIT_STATE_ACCOUNT_LIMIT = "account_limit"
# Objects the work needs are absent in its isolation: partial-clone blobs,
# a missing base commit, a ref that was described but never fetched.
UNIT_STATE_DATA_MISSING = "data_missing"
# The process is alive but the work is not moving: no new output past the
# threshold, or the same error and the same workaround repeating.
UNIT_STATE_PROGRESS_STALLED = "progress_stalled"
# The process ended without a verified result. An exit code of 0 with the
# required result missing is this state, never `verified`. So is a declared
# check the dispatcher ran and saw fail.
UNIT_STATE_FAILED = "failed"
# The process exited 0 and returned a validated result, but no verification
# was observed: none was declared, or none was asked to run. Nothing failed,
# and nothing was verified either, so this is neither `failed` nor `verified`
# (#2461). A reader retrying `failed` units must not retry this one; a reader
# that needs proof of the work must still check it.
UNIT_STATE_UNVERIFIED = "unverified"
# The result record was validated against the contract and its verification
# was observed. This is the only success state.
UNIT_STATE_VERIFIED = "verified"

UNIT_EXECUTION_STATES = (
    UNIT_STATE_RUNNING,
    UNIT_STATE_AWAITING_INPUT,
    UNIT_STATE_PERMISSION_BLOCKED,
    UNIT_STATE_ACCOUNT_LIMIT,
    UNIT_STATE_DATA_MISSING,
    UNIT_STATE_PROGRESS_STALLED,
    UNIT_STATE_FAILED,
    UNIT_STATE_UNVERIFIED,
    UNIT_STATE_VERIFIED,
)

# States that end a unit. Everything else is still someone's job to observe.
UNIT_TERMINAL_STATES = frozenset({UNIT_STATE_FAILED, UNIT_STATE_UNVERIFIED, UNIT_STATE_VERIFIED})

# States where the process may well be alive and the work is still not
# moving. A supervisor must treat these as needing intervention, not waiting.
UNIT_STUCK_STATES = frozenset(
    {
        UNIT_STATE_AWAITING_INPUT,
        UNIT_STATE_PERMISSION_BLOCKED,
        UNIT_STATE_ACCOUNT_LIMIT,
        UNIT_STATE_DATA_MISSING,
        UNIT_STATE_PROGRESS_STALLED,
    }
)

UNIT_EXECUTION_STATE_CLAIM_BOUNDARY = (
    "States describe what OMH observed about the unit's work, not whether its "
    "process exists. `running` requires new evidence; a live process with no "
    "new evidence is `progress_stalled`. `verified` requires a validated "
    "result record; an exit code alone never reaches it. `unverified` is a "
    "completed unit whose verification was never observed, not a failure and "
    "not a success. The one exception is "
    "a Hermes recovery attempt, whose file-tools-only child returns no result "
    "record: there `verified` means the child changed something, the "
    "dispatcher committed all of it, and the unit's declared checks passed on "
    "that commit."
)


def is_terminal(state: str) -> bool:
    return state in UNIT_TERMINAL_STATES


def is_stuck(state: str) -> bool:
    return state in UNIT_STUCK_STATES
