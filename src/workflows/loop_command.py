"""Whether a message opens with a loop command (`loop ...`, `/loop ...`, `omh loop ...`).

Split out of `goal_loop` so the chat router reads the command without importing the loop engine and the goal
ledger behind it on every fresh process: those cost about a tenth of a second on import and the router only
needs the two patterns below. `goal_loop` re-exports both names.
"""

from __future__ import annotations

import re

LOOP_COMMAND_RE = re.compile(r"^(?:\./|/|\$)?loop(?:\s|$)")
OMH_LOOP_COMMAND_RE = re.compile(r"^omh\s+(?:loop|루프)(?:\s|$)")


def explicit_loop_invocation_signal(goal_summary: str) -> bool:
    normalized = goal_summary.strip().casefold()
    if not normalized:
        return False
    if LOOP_COMMAND_RE.match(normalized):
        return True
    if OMH_LOOP_COMMAND_RE.match(normalized):
        return True
    return False
