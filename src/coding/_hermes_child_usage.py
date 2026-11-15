"""Private reader for a Hermes child's usage ledger.

Hermes writes its ``-z --usage-file`` report for ``-z/--oneshot`` alone, and
that mode cannot read a prompt from stdin (#1824). The child this package
spawns runs ``hermes chat --query-file - --quiet`` instead, so the report is
never written (#1831). The numbers the report would have carried are still
persisted: every API call of the turn queues its token deltas, priced cost,
``cost_status`` and ``cost_source`` into the child's ``sessions`` row of
``$HERMES_HOME/state.db`` (Hermes ``agent/turn_usage.py`` →
``SessionDB.queue_token_counts``), drained at turn finalize and again when the
quiet CLI exits. The dispatcher hands every child a disposable, exclusive
``HERMES_HOME``, so after the child exits and before that home is removed,
every ``sessions`` row in the file is this child's spend and nothing else's.
The child runs with ``--toolsets file --safe-mode``, so no delegate subagent
opens a row of its own and a context-compression rotation is the only source
of a second row; summing all rows therefore reproduces the agent's own
cumulative counters, which is what the ``-z`` report summarized. That
equivalence depends on the toolset restriction: a delegate child writes its
own ``sessions`` row, and the ``-z`` main-loop keys exclude subagent tokens
while its cost includes them, so a later ``--toolsets`` widening that admits
delegation has to revisit this sum.

This is a read-only coupling to a Hermes-private file shape. The columns read
here have been in the ``sessions`` table since Hermes 2026-04 (the cost trio
2026-03), before the ``>=0.21.1`` floor the plugin bundle declares; the
compatibility note lives in ``CONTEXT.md`` (Host surfaces OMH reads). When the
shape moves, this read goes quiet -- ``usage`` stays empty rather than zero --
and no field is estimated.
"""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3
from typing import Final

from ..quality.hermes_state import open_state_db_readonly
from ..system.metadata_safety import is_sensitive_metadata_text

_COUNT_COLUMNS: Final = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "api_call_count",
)
# ``sessions`` column -> usage key, in the vocabulary the ``-z`` report used
# (``hermes_cli/oneshot.py`` ``_USAGE_KEYS``), which is what the observation
# builder (``commands/hermes_child_observations.py``) already reads.
_TEXT_COLUMNS: Final = (
    ("model", "model"),
    ("billing_provider", "provider"),
    ("cost_status", "cost_status"),
    ("cost_source", "cost_source"),
)
_MAX_TEXT_CHARS: Final = 200
_SELECT: Final = (
    "SELECT id, " + ", ".join((*_COUNT_COLUMNS, "estimated_cost_usd", *(column for column, _key in _TEXT_COLUMNS)))
    + " FROM sessions ORDER BY started_at, rowid"
)


class _StateDbUnreadable(ValueError):
    """The disposable home holds no readable ``state.db``."""


def state_session_ids(hermes_home: Path) -> frozenset[str]:
    """The ``sessions`` ids already in a home, so a later read can leave them out."""
    try:
        _path, connection = open_state_db_readonly(hermes_home, error=_StateDbUnreadable)
    except (_StateDbUnreadable, OSError):
        return frozenset()
    try:
        return frozenset(str(row[0]) for row in connection.execute("SELECT id FROM sessions").fetchall())
    except sqlite3.Error:
        return frozenset()
    finally:
        connection.close()


def read_hermes_child_usage(
    hermes_home: Path,
    *,
    exclude: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Sum the ``sessions`` rows of a finished child's disposable home into one usage record.

    Empty when the database is missing, is not a database, lacks the columns,
    or records no API call at all: a child that never reached a provider has
    nothing to bill, and an empty mapping is how ``usage`` says so (never a
    zero). Text values are bounded and screened the way the removed usage-file
    reader screened them, so a credential-shaped model name cannot ride out in
    an observation.
    """
    try:
        _path, connection = open_state_db_readonly(hermes_home, error=_StateDbUnreadable)
    except (_StateDbUnreadable, OSError):
        return {}
    try:
        rows = [
            row[1:] for row in connection.execute(_SELECT).fetchall()
            if str(row[0]) not in exclude
        ]
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return summarize_session_rows(rows)


def summarize_session_rows(rows: list[tuple[object, ...]]) -> dict[str, object]:
    """Fold ``sessions`` rows (in ``started_at`` order) into the ``-z`` report vocabulary.

    Counts and cost are summed across rows; for ``model``, ``provider``,
    ``cost_status`` and ``cost_source`` the latest row's non-``None`` value
    wins, mirroring Hermes' own last-call-wins update of those columns.
    """
    counts = {column: 0 for column in _COUNT_COLUMNS}
    cost_total: float | None = None
    text: dict[str, str] = {}
    for row in rows:
        values = dict(zip((*_COUNT_COLUMNS, "estimated_cost_usd", *(column for column, _key in _TEXT_COLUMNS)), row))
        for column in _COUNT_COLUMNS:
            count = _count(values.get(column))
            if count is not None:
                counts[column] += count
        cost = _amount(values.get("estimated_cost_usd"))
        if cost is not None:
            cost_total = (cost_total or 0.0) + cost
        for column, key in _TEXT_COLUMNS:
            # The latest row's value wins: a compression rotation carries the
            # route forward, and the row that priced last says how.
            value = _text(values.get(column))
            if value is not None:
                text[key] = value
    if counts["api_call_count"] <= 0:
        return {}
    usage: dict[str, object] = {column: counts[column] for column in _COUNT_COLUMNS if column != "api_call_count"}
    usage["total_tokens"] = counts["input_tokens"] + counts["output_tokens"]
    usage["api_calls"] = counts["api_call_count"]
    if cost_total is not None:
        usage["estimated_cost_usd"] = cost_total
    usage.update(text)
    return usage


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _amount(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT_CHARS:
        return None
    if is_sensitive_metadata_text(value):
        return None
    return value
