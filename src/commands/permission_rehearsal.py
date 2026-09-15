from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..installer import OmhError
from ..workflows.permission_rehearsal import (
    PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION,
    read_planned_calls,
    rehearse_planned_calls,
)
from .common import _paths, _print_json


def cmd_ops_permission_rehearse(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        planned = read_planned_calls(Path(args.plan).expanduser())
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    payload = rehearse_planned_calls(
        planned,
        omh_home=paths.omh_home,
        hermes_home=paths.hermes_home,
    )
    _print_json(payload)
    return _permission_rehearsal_exit_code(payload)


def _permission_rehearsal_exit_code(payload: Any) -> int:
    """0 only when the local rules refuse none of the planned calls.

    0 says "no rule refuses these", never "these are allowed". Unknown rows
    do not move the status, and that is deliberate: every call OMH cannot
    read a per-tool approval declaration for is unknown -- today that is
    every call no rule refuses -- and a status that can never be 0 teaches a
    wrapper to stop reading it. The payload carries the other half: unknown
    rows say why, and no count treats one as permitted.

    1 when a planned call is refused. An unattended batch that would be
    blocked partway through should not start, and a shell that reads only the
    status is the caller this command exists for. A refusal outranks a rules
    defect because it is the concrete finding; the defect count is still in
    the payload.

    3 when the rules file is present but defective. The refusal tier then
    answered from a policy the operator did not write, so its "nothing
    refused" is not a green light; `omh ops toolcall-rules-validate` names
    the defects. A missing rules file is not a defect -- its absence is the
    opt-in not taken, and no rule refusing anything is the truth. Not 2:
    `main` already returns 2 for an OmhError, so a wrapper reading 2 cannot
    tell a plan it could not parse from a rehearsal that ran.

    Generic failure signals -- a refused or interrupted run, or a unit
    carrying a failure kind -- are never success either, so this mapper
    cannot be passed by ignoring them.
    """
    summary = payload if isinstance(payload, dict) else {}
    if summary.get("refused") or summary.get("interrupted"):
        return 1
    units = summary.get("units")
    if isinstance(units, list) and any(isinstance(unit, dict) and unit.get("failure_kind") for unit in units):
        return 1
    counts = summary.get("summary")
    if isinstance(counts, dict) and counts.get("refused"):
        return 1
    rules = summary.get("rules")
    if isinstance(rules, dict) and rules.get("defect_count"):
        return 3
    return 0


def add_ops_permission_rehearsal_command(ops_sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    rehearse = ops_sub.add_parser(
        "permission-rehearse",
        help=(
            "Run a planned batch of tool calls through the local toolcall rules without "
            "executing anything, so a cron entry or unattended run shows which calls are "
            "refused, and whether an approval bypass is active, before it starts."
        ),
    )
    rehearse.add_argument(
        "--plan",
        required=True,
        help=(
            f"Plan file ({PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION}) listing the planned "
            "calls as objects with a `tool` name and optional `args`."
        ),
    )
    rehearse.set_defaults(func=cmd_ops_permission_rehearse)
