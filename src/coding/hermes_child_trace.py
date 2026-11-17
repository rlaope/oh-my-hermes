"""A metadata-only trace of what one paired-run Hermes child did.

Confirmed paired-run evaluation (`paired_run_arm_home`) is the only caller:
after the cell's child exits and while its arm home is still alive, the
dispatcher reads the child's new `sessions` rows and their `messages` from
that home's `state.db` and keeps counts and names only -- API calls, token
counts, the ordered tool NAMES, which skills `skill_view` opened, and the size
in characters of the system prompt and of the first request. No prompt,
reply, tool argument or tool result leaves the read; a `skill_view` argument
is parsed only to keep its `name`.

When the arm may delegate (`--arm-toolsets ... delegation`), Hermes' own
`delegate_task` children write `sessions` rows of their own (`source =
'subagent'`) into the same store. They count in the sums above, and the trace
also says how many there were, their API calls, how many ran at once (from
`started_at`/`ended_at`), and every model the new rows name
(`session_models`), so fan-in can refuse a child that ran another model.

The read is read-only (`mode=ro`, `immutable=1` when no `-wal`/`-shm`/`-journal`
sits beside the store), bounded, and never raises: a missing, locked or
unreadable store, or one holding no row of this child, yields no trace (None),
never a zero. A column or table the store lacks makes only its own field null.
The dispatcher signs the result into the routing observation as `cell_trace`;
a caller mapping can neither supply nor keep one (`hermes_child_receipts`).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Final

from ..plugin_bundle.omh.sqlite_readonly import connect_readonly
from ..system.metadata_safety import is_sensitive_metadata_text

CELL_TRACE_FIELDS: Final = frozenset(
    {
        "session_count",
        "api_call_count",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "total_tokens",
        "tool_call_count",
        "tool_names",
        "tool_names_truncated",
        "skill_view_count",
        "skill_view_names",
        "system_prompt_chars",
        "first_request_chars",
        "subagent_session_count",
        "subagent_api_call_count",
        "max_concurrent_subagents",
        "session_models",
    }
)
_TOKEN_COLUMNS: Final = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)
_COUNT_FIELDS: Final = (
    "session_count",
    "api_call_count",
    *_TOKEN_COLUMNS,
    "total_tokens",
    "tool_call_count",
    "skill_view_count",
    "system_prompt_chars",
    "first_request_chars",
    "subagent_session_count",
    "subagent_api_call_count",
    "max_concurrent_subagents",
)
MAX_TOOL_NAMES: Final = 200
MAX_SESSION_MODELS: Final = 10
SUBAGENT_SOURCE: Final = "subagent"
MAX_SKILL_NAMES: Final = 50
# A tool_calls cell larger than this is not parsed; the tool fields go null
# rather than undercount. A coding child's write_file arguments stay far below.
_MAX_TOOL_CALLS_BYTES: Final = 4 * 1024 * 1024
_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$")
UNRECOGNIZED_NAME: Final = "unrecognized"
_BUSY_SECONDS: Final = 0.5


@dataclass(frozen=True, slots=True)
class CellTrace:
    """Counts and names read from one child's rows; None means not recorded."""

    session_count: int
    api_call_count: int | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    tool_call_count: int | None
    tool_names: tuple[str, ...] | None
    tool_names_truncated: bool
    skill_view_count: int | None
    skill_view_names: tuple[str, ...] | None
    system_prompt_chars: int | None
    first_request_chars: int | None
    # Hermes `delegate_task` children among the rows; None when the store
    # lacks the column that says so, never zero.
    subagent_session_count: int | None = None
    subagent_api_call_count: int | None = None
    max_concurrent_subagents: int | None = None
    session_models: tuple[str, ...] | None = None

    def to_record(self) -> dict[str, int | bool | list[str] | None]:
        return {
            "session_count": self.session_count,
            "api_call_count": self.api_call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "tool_call_count": self.tool_call_count,
            "tool_names": None if self.tool_names is None else list(self.tool_names),
            "tool_names_truncated": self.tool_names_truncated,
            "skill_view_count": self.skill_view_count,
            "skill_view_names": None if self.skill_view_names is None else list(self.skill_view_names),
            "system_prompt_chars": self.system_prompt_chars,
            "first_request_chars": self.first_request_chars,
            "subagent_session_count": self.subagent_session_count,
            "subagent_api_call_count": self.subagent_api_call_count,
            "max_concurrent_subagents": self.max_concurrent_subagents,
            "session_models": None if self.session_models is None else list(self.session_models),
        }


def read_hermes_child_trace(hermes_home: Path, *, exclude: frozenset[str] = frozenset()) -> CellTrace | None:
    """The trace of every `sessions` row in `hermes_home` not in `exclude`, or None."""
    path = Path(hermes_home) / "state.db"
    if not path.is_file():
        return None
    try:
        connection = connect_readonly(path, timeout=_BUSY_SECONDS, immutable=_no_connection_open(path))
    except sqlite3.Error:
        return None
    try:
        return _trace(connection, exclude)
    except (sqlite3.Error, ValueError, OverflowError):
        return None
    finally:
        connection.close()


def _no_connection_open(path: Path) -> bool:
    # Same rule as the TUI's board reader: a WAL store with no `-wal`/`-shm`
    # beside it has no open connection, and a `mode=ro` open would create both.
    return not any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def _columns(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall())


def _trace(connection: sqlite3.Connection, exclude: frozenset[str]) -> CellTrace | None:
    session_columns = _columns(connection, "sessions")
    if "id" not in session_columns:
        return None
    order = "started_at, rowid" if "started_at" in session_columns else "rowid"
    ids = [
        str(row[0])
        for row in connection.execute(f"SELECT id FROM sessions ORDER BY {order}").fetchall()
        if str(row[0]) not in exclude
    ]
    if not ids:
        return None
    marks = ",".join("?" for _ in ids)
    counts: dict[str, int | None] = {}
    for column in ("api_call_count", *_TOKEN_COLUMNS):
        if column in session_columns:
            (total,) = connection.execute(
                f"SELECT SUM(COALESCE({column}, 0)) FROM sessions WHERE id IN ({marks})", ids
            ).fetchone()
            counts[column] = _count(total)
        else:
            counts[column] = None
    input_tokens, output_tokens = counts["input_tokens"], counts["output_tokens"]
    total_tokens = None if input_tokens is None or output_tokens is None else input_tokens + output_tokens
    tools = _tool_calls(connection, ids, marks)
    tool_names, skill_names = tools if tools is not None else (None, None)
    subagents = _subagents(connection, session_columns, ids, marks)
    return CellTrace(
        session_count=len(ids),
        api_call_count=counts["api_call_count"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=counts["cache_read_tokens"],
        cache_write_tokens=counts["cache_write_tokens"],
        reasoning_tokens=counts["reasoning_tokens"],
        total_tokens=total_tokens,
        tool_call_count=None if tool_names is None else len(tool_names),
        tool_names=None if tool_names is None else tuple(tool_names[:MAX_TOOL_NAMES]),
        tool_names_truncated=tool_names is not None and len(tool_names) > MAX_TOOL_NAMES,
        skill_view_count=None if skill_names is None else len(skill_names),
        skill_view_names=None if skill_names is None else tuple(skill_names[:MAX_SKILL_NAMES]),
        system_prompt_chars=_system_prompt_chars(connection, session_columns, ids[0]),
        first_request_chars=_first_request_chars(connection, ids, marks),
        subagent_session_count=subagents[0],
        subagent_api_call_count=subagents[1],
        max_concurrent_subagents=subagents[2],
        session_models=_session_models(connection, session_columns, ids, marks),
    )


def _subagents(
    connection: sqlite3.Connection, columns: frozenset[str], ids: list[str], marks: str
) -> tuple[int | None, int | None, int | None]:
    """(children, their API calls, most children open at once); each None when unreadable."""
    if "source" not in columns:
        return None, None, None
    rows = connection.execute(
        f"SELECT {', '.join(_column_or_null(columns, name) for name in ('api_call_count', 'started_at', 'ended_at'))}"
        f" FROM sessions WHERE source = ? AND id IN ({marks})",
        [SUBAGENT_SOURCE, *ids],
    ).fetchall()
    calls: int | None = 0 if "api_call_count" in columns else None
    for row in rows:
        if calls is not None:
            calls += _count(row[0]) or 0
    return len(rows), calls, _max_overlap([(row[1], row[2]) for row in rows])


def _column_or_null(columns: frozenset[str], name: str) -> str:
    return name if name in columns else "NULL"


def _max_overlap(spans: list[tuple[object, object]]) -> int | None:
    """The most `[started_at, ended_at)` spans open at one instant; None if any end is unknown."""
    events: list[tuple[float, int]] = []
    for start, end in spans:
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (start, end)):
            return None
        events.extend(((float(start), 1), (float(end), -1)))  # type: ignore[arg-type]
    # An end sorts before a start at the same instant: back-to-back is not overlap.
    open_now = most = 0
    for _at, step in sorted(events):
        open_now += step
        most = max(most, open_now)
    return most


def _session_models(
    connection: sqlite3.Connection, columns: frozenset[str], ids: list[str], marks: str
) -> tuple[str, ...] | None:
    """Sorted distinct models of the new rows; a row naming none reads `unrecognized`.

    More distinct models than the cap reads as unknown (None), never as a
    shortened list that could hide one.
    """
    if "model" not in columns:
        return None
    rows = connection.execute(f"SELECT DISTINCT model FROM sessions WHERE id IN ({marks})", ids).fetchall()
    models = tuple(sorted({_safe_name(row[0]) for row in rows}))
    return models if len(models) <= MAX_SESSION_MODELS else None


def _tool_calls(
    connection: sqlite3.Connection, ids: list[str], marks: str
) -> tuple[list[str], list[str]] | None:
    columns = _columns(connection, "messages")
    if not {"session_id", "role", "tool_calls"} <= columns:
        return None
    rows = connection.execute(
        "SELECT CASE WHEN length(CAST(tool_calls AS BLOB)) <= ? THEN tool_calls END, tool_calls IS NOT NULL "
        f"FROM messages WHERE role = 'assistant' AND session_id IN ({marks}) ORDER BY id",
        [_MAX_TOOL_CALLS_BYTES, *ids],
    ).fetchall()
    names: list[str] = []
    skills: list[str] = []
    for raw, present in rows:
        if not present:
            continue
        if raw is None:
            return None
        try:
            calls = json.loads(raw) if isinstance(raw, (str, bytes)) else None
        except (ValueError, RecursionError):
            return None
        if calls is None:
            continue
        for call in calls if isinstance(calls, list) else [calls]:
            name, arguments = _call_parts(call)
            names.append(name)
            if name == "skill_view":
                skills.append(_skill_name(arguments))
    return names, skills


def _call_parts(call: object) -> tuple[str, object]:
    if not isinstance(call, dict):
        return UNRECOGNIZED_NAME, None
    function = call.get("function")
    source = function if isinstance(function, dict) else call
    return _safe_name(source.get("name")), source.get("arguments")


def _skill_name(arguments: object) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (ValueError, RecursionError):
            return UNRECOGNIZED_NAME
    return _safe_name(arguments.get("name")) if isinstance(arguments, dict) else UNRECOGNIZED_NAME


def _safe_name(value: object) -> str:
    if isinstance(value, str) and _NAME.fullmatch(value) and not is_sensitive_metadata_text(value):
        return value
    return UNRECOGNIZED_NAME


def _system_prompt_chars(connection: sqlite3.Connection, columns: frozenset[str], session_id: str) -> int | None:
    if "system_prompt" not in columns:
        return None
    stored = "s.system_prompt"
    if "system_prompt_hash" in columns and {"hash", "prompt"} <= _columns(connection, "system_prompts"):
        stored = "COALESCE(s.system_prompt, (SELECT p.prompt FROM system_prompts p WHERE p.hash = s.system_prompt_hash))"
    row = connection.execute(f"SELECT length({stored}) FROM sessions s WHERE s.id = ?", (session_id,)).fetchone()
    return _count(row[0]) if row else None


def _first_request_chars(connection: sqlite3.Connection, ids: list[str], marks: str) -> int | None:
    columns = _columns(connection, "messages")
    if not {"session_id", "role", "content"} <= columns:
        return None
    # `api_content` is the exact string sent when Hermes kept it; injected
    # per-turn context lands there, so it is preferred over the stored text.
    text = "COALESCE(api_content, content)" if "api_content" in columns else "content"
    row = connection.execute(
        f"SELECT length({text}) FROM messages WHERE role = 'user' AND session_id IN ({marks}) ORDER BY id LIMIT 1",
        ids,
    ).fetchone()
    return _count(row[0]) if row else None


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def cell_trace_errors(value: object) -> list[str]:
    """Shape errors of a persisted `cell_trace` object (closed field set)."""
    if not isinstance(value, dict) or set(value) != CELL_TRACE_FIELDS:
        return ["cell_trace must be an object with exactly the cell trace fields"]
    errors: list[str] = []
    for field in _COUNT_FIELDS:
        item = value.get(field)
        if item is not None and _count(item) is None:
            errors.append(f"cell_trace.{field} must be a non-negative integer or null")
    if _count(value.get("session_count")) is None:
        errors.append("cell_trace.session_count must be a non-negative integer")
    if not isinstance(value.get("tool_names_truncated"), bool):
        errors.append("cell_trace.tool_names_truncated must be a boolean")
    for field, limit in (
        ("tool_names", MAX_TOOL_NAMES),
        ("skill_view_names", MAX_SKILL_NAMES),
        ("session_models", MAX_SESSION_MODELS),
    ):
        names = value.get(field)
        if names is None:
            continue
        if (
            not isinstance(names, list)
            or len(names) > limit
            or not all(isinstance(name, str) and _safe_name(name) == name for name in names)
        ):
            errors.append(f"cell_trace.{field} must be a bounded list of metadata-only names or null")
    return errors


def parse_cell_trace(value: object) -> CellTrace | None:
    if cell_trace_errors(value) or not isinstance(value, dict):
        return None
    names = value["tool_names"]
    skills = value["skill_view_names"]
    models = value["session_models"]
    return CellTrace(
        session_count=value["session_count"],
        api_call_count=value["api_call_count"],
        input_tokens=value["input_tokens"],
        output_tokens=value["output_tokens"],
        cache_read_tokens=value["cache_read_tokens"],
        cache_write_tokens=value["cache_write_tokens"],
        reasoning_tokens=value["reasoning_tokens"],
        total_tokens=value["total_tokens"],
        tool_call_count=value["tool_call_count"],
        tool_names=None if names is None else tuple(names),
        tool_names_truncated=value["tool_names_truncated"],
        skill_view_count=value["skill_view_count"],
        skill_view_names=None if skills is None else tuple(skills),
        system_prompt_chars=value["system_prompt_chars"],
        first_request_chars=value["first_request_chars"],
        subagent_session_count=value["subagent_session_count"],
        subagent_api_call_count=value["subagent_api_call_count"],
        max_concurrent_subagents=value["max_concurrent_subagents"],
        session_models=None if models is None else tuple(models),
    )
