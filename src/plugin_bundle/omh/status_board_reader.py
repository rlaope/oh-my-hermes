"""Standalone running-work board reader for the vendored plugin bundle (`omh_running_work_board/v1`).

`pre_llm_call` needs to know whether multiple coding units are running right
now so it can surface that automatically, without the user asking. The real
projection lives in `omh.coding.status_board`, but the plugin bundle cannot
import `omh.*` -- the Hermes process only has `src/plugin_bundle/omh/` on its
path, never the rest of the `omh` package tree. Without a standalone reader,
the hook would either silently see nothing or have to import a module that
does not exist at runtime and crash the hook on every call. This module reads
the same on-disk markers directly with `json.load` and narrow excepts, the
same standalone-file pattern `tools/capability_tool.py` already uses for the
capability-family sidecar.

Sources, in merge precedence order (matches
`omh.coding.status_board.SOURCE_ORDER`):

- `<omh_home>/coding/fanout/<fanout_id>/inflight/<unit_id>.json` -- one marker
  per unit currently dispatched, written before the blocking spawn and removed
  after it (see `omh.coding.inflight`). A marker wins over a dispatch-summary
  row for the same unit because it means the unit is still running.
- `<omh_home>/coding/fanout/<fanout_id>/dispatch_summary.json` -- terminal or
  in-progress status for units a fanout has already reported on, used to fill
  in units the marker directory does not (or no longer) cover.

Boundaries, in order of importance:

- Presence is not liveness. A marker only proves some process wrote it and has
  not removed it; a crashed dispatcher leaves it behind. This reader never
  claims a unit is alive, only that a marker or summary row said `running`.
- Absent is not unreadable. A marker directory that does not exist yet, or a
  dispatch summary not written yet, is the ordinary shape of a fanout that
  has not run or has not finished dispatching -- reported as `absent`. A file
  that exists but fails to parse as a JSON object is `unreadable`, a genuine
  read failure worth counting separately so a filesystem or corruption problem
  is never hidden behind ordinary "nothing here yet" churn.
- Never raise. Every filesystem read is wrapped in a narrow
  `except (OSError, ValueError)`; a malformed or vanished file is skipped
  (and where relevant counted as unreadable) instead of failing the whole
  board. A hook that raises disappears silently under Hermes's own
  try/except-and-log wrapper, so raising here would look identical to the
  board simply having nothing to report.
- Metadata only. Unit ids, labels, runtimes, and model labels are read; no
  prompts, no raw output, no worktree paths.
- Reporting only. Nothing here is persisted, dispatched, or fed back into a
  route; it is not result, review, CI, merge-readiness, or merge evidence.
"""

from __future__ import annotations

from . import runtime_paths

import errno
import hashlib
import json
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - absent on Windows.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - present only on Windows.
    msvcrt = None

RUNNING_WORK_BOARD_SCHEMA_VERSION: Final[str] = "omh_running_work_board/v1"

RUNNING_WORK_CLAIM_BOUNDARY: Final[str] = (
    "Running-work rows are metadata read from local in-flight markers and dispatch summaries. "
    "Presence is not liveness. This is not result, review, CI, merge-readiness, or merge evidence."
)

DEFAULT_LIMIT: Final[int] = 6

# Must match `omh.coding.inflight.INFLIGHT_MARKER_SCHEMA_VERSION`. Repeated
# here rather than imported because the plugin bundle cannot import `omh.*`.
_INFLIGHT_MARKER_SCHEMA_VERSION: Final[str] = "omh_inflight_marker/v1"

_FANOUT_SUBDIR: Final[str] = "fanout"
_INFLIGHT_DIR_NAME: Final[str] = "inflight"
_DISPATCH_SUMMARY_NAME: Final[str] = "dispatch_summary.json"
_FANOUT_CONTRACT_NAME: Final[str] = "fanout_contract.json"

# Closed status vocabulary a dispatch-summary row can carry. Anything else
# collapses to `prepared_not_observed`, mirroring
# `omh.coding.status_board.normalize_status`.
_STATUS_VOCABULARY: Final[tuple[str, ...]] = (
    "running",
    "completed",
    "failed",
    "worktree_failed",
    "prepared_not_observed",
)

# Bound for a status word the vocabulary above refused. Mirrors
# `omh.coding.status_board._STATUS_SOURCE_LIMIT`; the word rides in the rendered
# STATUS cell, so dropping it here would make this reader the one surface where
# "an executor said something we do not know" still reads as "nobody watched".
_STATUS_SOURCE_LIMIT: Final[int] = 80

_MODEL_DEFAULT_LABEL: Final[str] = "executor default"

# `omh.runtime.context_budget` owns this ledger file and schema; repeated here
# because the plugin bundle cannot import `runtime.*` either. Writing into the
# same file under a dedicated bucket key means this hook's suppression
# bookkeeping shares the ledger that module already owns instead of adding a
# second one.
_CONTEXT_BUDGET_LEDGER_NAME: Final[str] = "context_budget.json"
_CONTEXT_BUDGET_SCHEMA_VERSION: Final[str] = "omh_run_context_budget/v1"
_CONTEXT_BUDGET_LOCK_TIMEOUT_SECONDS: Final[float] = 0.1
_CONTEXT_BUDGET_LOCK_POLL_INTERVAL: Final[float] = 0.001
_LOCK_BUSY_ERRNOS: Final[frozenset[int]] = frozenset(
    {errno.EACCES, errno.EAGAIN, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}
)

# Not a real fanout/run id -- `FANOUT_ID_PATTERN` and unit-id patterns never
# produce a dunder-wrapped string, so this bucket can never collide with a
# real one. Same convention as `context_budget.PROGRESS_STATUS_LEDGER_KEY`,
# used there for the same reason: this surface spans every fanout rather than
# naming one run.
RUNNING_WORK_LEDGER_KEY: Final[str] = "__pre_llm_running_work_board__"
RUNNING_WORK_SURFACE: Final[str] = "pre_llm_call_running_work_board"


def read_running_work_board(omh_home: str | Path | None, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Project every locally observed in-flight coding unit into one board payload. Never raises."""
    effective_limit = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else 0
    home = _home_dir(omh_home)
    fanout_root = home / "coding" / _FANOUT_SUBDIR
    root_status, fanout_dirs = _list_fanout_dirs(fanout_root)

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    inflight_unreadable = 0
    dispatch_unreadable = 0
    for fanout_dir, fanout_id in fanout_dirs:
        titles = _unit_titles(fanout_dir)
        inflight_unreadable += _merge_inflight(merged, fanout_dir, fanout_id, titles)
        dispatch_unreadable += _merge_dispatch_summary(merged, fanout_dir, fanout_id, titles)

    units = sorted(merged.values(), key=_sort_key)
    running_count = sum(1 for unit in units if unit["status"] == "running")
    # Counted apart from `running_count`, which is the DISPATCH tally this
    # block's own >= 2 gate reads; its meaning stays put. The rendered line is
    # what must not fold a stuck unit into "N running".
    stuck_count = sum(1 for unit in units if str(unit.get("unit_state", "") or "") in _STUCK_STATES)
    shown = units[:effective_limit]
    return {
        "schema_version": RUNNING_WORK_BOARD_SCHEMA_VERSION,
        "running_count": running_count,
        "stuck_count": stuck_count,
        "unit_count": len(units),
        "units": shown,
        "truncated": len(units) > len(shown),
        "omitted_count": max(0, len(units) - len(shown)),
        "sources": {
            "fanout_root": root_status,
            "fanout_dirs_scanned": len(fanout_dirs),
            "inflight_markers_unreadable": inflight_unreadable,
            "dispatch_summaries_unreadable": dispatch_unreadable,
        },
        "claim_boundary": RUNNING_WORK_CLAIM_BOUNDARY,
    }


def render_running_work_block_text(board: dict[str, Any]) -> str:
    """Compact model-facing text for a board whose `running_count` is >= 2.

    Rows are already bounded by `read_running_work_board`'s `limit`; when that
    cuts units off, the omission is stated as its own line rather than the
    list just stopping, so a reader never mistakes a truncated board for a
    complete one.
    """
    running_count = int(board.get("running_count", 0) or 0)
    unit_count = int(board.get("unit_count", 0) or 0)
    # Same split as `omh.coding.status_board._header_line`: a stuck unit is
    # subtracted from the headline and named, never folded into "N running".
    stuck_count = min(int(board.get("stuck_count", 0) or 0), running_count)
    moving = running_count - stuck_count
    stuck_text = f", {stuck_count} stuck" if stuck_count else ""
    units = [unit for unit in board.get("units", []) if isinstance(unit, dict)]
    lines = [f"[OMH] Running coding work: {moving} running{stuck_text} of {unit_count} observed."]
    for unit in units:
        lines.append(
            f"- {unit.get('fanout_id', 'unknown')}/{unit.get('unit_id', 'unknown')}: "
            f"{unit.get('runtime', 'unknown')} ({unit.get('model_label', _MODEL_DEFAULT_LABEL)}) "
            f"— {_status_text(unit)}"
        )
    if board.get("truncated"):
        omitted = int(board.get("omitted_count", 0) or 0)
        lines.append(f"Showing {len(units)} of {unit_count} units; {omitted} not shown because of the display limit.")
    lines.append("Use `omh coding status-board` for full detail.")
    lines.append(str(board.get("claim_boundary", "")))
    return "\n".join(lines)


def running_work_board_fingerprint(board: dict[str, Any]) -> str:
    """Hash of the board a reader would act on. Mirrors `context_budget.payload_fingerprint`."""
    return hashlib.sha256(json.dumps(board, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def last_running_work_board_fingerprint(omh_home: str | Path | None) -> str:
    """Fingerprint of the running-work board this hook last emitted, or "" if none.

    Reads the ledger `omh.runtime.context_budget.record_context_emission`
    already owns, under `RUNNING_WORK_LEDGER_KEY`, so a second identical board
    is recognized as unchanged and not re-injected into every following turn --
    mirrors `context_budget.unchanged_progress_status_payload`'s intent without
    importing it, since the plugin bundle cannot import `runtime.*`.
    """
    ledger = _read_context_budget_ledger(_context_budget_ledger_path(omh_home))
    runs = ledger.get("runs")
    entry = runs.get(RUNNING_WORK_LEDGER_KEY) if isinstance(runs, dict) else None
    if not isinstance(entry, dict):
        return ""
    fingerprints = entry.get("payload_fingerprints")
    if not isinstance(fingerprints, dict):
        return ""
    return str(fingerprints.get(RUNNING_WORK_SURFACE, "") or "")


def record_running_work_board_emission(omh_home: str | Path | None, *, byte_count: int, fingerprint: str) -> None:
    """Record one running-work block emission. Best-effort; never raises.

    A write failure here must never break `pre_llm_call`: losing this
    bookkeeping only means the next turn re-emits an unchanged block, which is
    the same cost the suppression exists to avoid, not a broken hook.
    """
    path = _context_budget_ledger_path(omh_home)
    try:
        with _context_budget_ledger_lock(path):
            ledger = _read_context_budget_ledger(path)
            runs = ledger.get("runs")
            runs = dict(runs) if isinstance(runs, dict) else {}
            entry = runs.get(RUNNING_WORK_LEDGER_KEY)
            entry = dict(entry) if isinstance(entry, dict) else {}
            surfaces = dict(entry.get("surfaces")) if isinstance(entry.get("surfaces"), dict) else {}
            fingerprints = (
                dict(entry.get("payload_fingerprints"))
                if isinstance(entry.get("payload_fingerprints"), dict)
                else {}
            )
            entry["emitted_bytes"] = _safe_int(entry.get("emitted_bytes")) + max(0, int(byte_count))
            entry["call_count"] = _safe_int(entry.get("call_count")) + 1
            surfaces[RUNNING_WORK_SURFACE] = _safe_int(surfaces.get(RUNNING_WORK_SURFACE)) + 1
            entry["surfaces"] = surfaces
            if fingerprint:
                fingerprints[RUNNING_WORK_SURFACE] = fingerprint
            entry["payload_fingerprints"] = fingerprints
            entry["updated_at"] = _utc_now()
            runs[RUNNING_WORK_LEDGER_KEY] = entry
            payload = {
                "schema_version": _CONTEXT_BUDGET_SCHEMA_VERSION,
                "updated_at": entry["updated_at"],
                "runs": runs,
            }
            _write_json_best_effort(path, payload)
    except (OSError, ValueError, TypeError):
        return


def _list_fanout_dirs(fanout_root: Path) -> tuple[str, list[tuple[Path, str]]]:
    """Every immediate subdirectory of the fanout root, plus its own read status.

    Distinguishes a fanout root that was never created (`absent`, the ordinary
    shape of "no coding fanout has ever run here") from one that exists but
    could not be listed (`unreadable`, e.g. a file sitting where a directory
    is expected, or a permission failure) -- the two mean different things and
    collapsing them would hide the second behind the first.
    """
    try:
        if not fanout_root.exists():
            return "absent", []
        if not fanout_root.is_dir():
            return "unreadable", []
        children = sorted(fanout_root.iterdir())
    except (OSError, ValueError):
        return "unreadable", []
    return "present", [(child, child.name) for child in children if child.is_dir() and not child.is_symlink()]


def _read_json_object_result(path: Path) -> tuple[dict[str, Any] | None, str]:
    """Read one JSON object file. Returns `(payload, status)`, `status` in
    `{"present", "absent", "unreadable"}`. Never raises.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None, "absent"
    except (OSError, ValueError):
        return None, "unreadable"
    if not isinstance(payload, dict):
        return None, "unreadable"
    return payload, "present"


def _unit_titles(fanout_dir: Path) -> dict[str, str]:
    payload, status = _read_json_object_result(fanout_dir / _FANOUT_CONTRACT_NAME)
    if status != "present" or payload is None:
        return {}
    titles: dict[str, str] = {}
    for unit in payload.get("units", []):
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id", "") or "")
        title = str(unit.get("title", "") or "")
        if unit_id and title:
            titles[unit_id] = title
    return titles


def _merge_inflight(
    merged: dict[tuple[str, str], dict[str, Any]],
    fanout_dir: Path,
    fanout_id: str,
    titles: dict[str, str],
) -> int:
    try:
        marker_paths = sorted((fanout_dir / _INFLIGHT_DIR_NAME).iterdir())
    except (OSError, ValueError):
        return 0
    unreadable = 0
    for marker_path in marker_paths:
        if marker_path.suffix != ".json":
            continue
        unit_id = marker_path.stem
        if not unit_id:
            continue
        payload, status = _read_json_object_result(marker_path)
        if status == "absent":
            # Cleared between listing and reading -- the unit finished and its
            # dispatcher removed the marker; a benign race, not corruption.
            continue
        if status == "unreadable" or payload is None or str(payload.get("schema_version", "")) != _INFLIGHT_MARKER_SCHEMA_VERSION:
            unreadable += 1
            continue
        merged[(fanout_id, unit_id)] = _unit_row(
            fanout_id=fanout_id,
            unit_id=unit_id,
            label=titles.get(unit_id, unit_id),
            runtime=str(payload.get("owner", "") or ""),
            model=str(payload.get("model", "") or ""),
            reasoning_effort=str(payload.get("reasoning_effort", "") or ""),
            # The dispatch word, not a claim about the work; `unit_state`
            # beside it is what says whether the work is moving.
            status="running",
            unit_state=str(payload.get("unit_state", "") or ""),
            state_reason=str(payload.get("state_reason", "") or ""),
            stalled_for_seconds=str(payload.get("stalled_for_seconds", "") or ""),
        )
    return unreadable


def _merge_dispatch_summary(
    merged: dict[tuple[str, str], dict[str, Any]],
    fanout_dir: Path,
    fanout_id: str,
    titles: dict[str, str],
) -> int:
    payload, status = _read_json_object_result(fanout_dir / _DISPATCH_SUMMARY_NAME)
    if status == "absent":
        # Fanout dispatched but has not finished (or started) writing its
        # summary yet -- the ordinary shape of "still running", not a failure.
        return 0
    if status == "unreadable" or payload is None:
        return 1
    units = payload.get("units", [])
    if not isinstance(units, list):
        return 1
    for entry in units:
        if not isinstance(entry, dict):
            continue
        unit_id = str(entry.get("unit_id", "") or "")
        if not unit_id:
            continue
        key = (fanout_id, unit_id)
        if key in merged:
            # An in-flight marker already reported this unit as running; a
            # marker always wins over a dispatch-summary row for the same unit.
            continue
        merged[key] = _unit_row(
            fanout_id=fanout_id,
            unit_id=unit_id,
            label=titles.get(unit_id, unit_id),
            runtime=str(entry.get("owner", "") or ""),
            model=str(entry.get("model", "") or ""),
            reasoning_effort=str(entry.get("reasoning_effort", "") or ""),
            status=_normalize_status(entry.get("status")),
            unmapped_source_status=_unmapped_status_source(entry.get("status")),
        )
    return 0


def _unit_row(
    *,
    fanout_id: str,
    unit_id: str,
    label: str,
    runtime: str,
    model: str,
    reasoning_effort: str,
    status: str,
    unmapped_source_status: str = "",
    unit_state: str = "",
    state_reason: str = "",
    stalled_for_seconds: str = "",
) -> dict[str, Any]:
    row = {
        "fanout_id": fanout_id,
        "unit_id": unit_id,
        "label": label or unit_id or "unknown",
        "runtime": runtime or "unknown",
        "model_label": _model_label(model, reasoning_effort),
        "status": status,
    }
    # Absent unless a word was actually discarded, so an absent key means the
    # status was accepted verbatim -- never that nothing was checked.
    if unmapped_source_status:
        row["unmapped_source_status"] = unmapped_source_status
    # Absent unless a stdout snapshot was actually assessed. An absent
    # `unit_state` means nothing observed the work, which is exactly what a
    # reader must not confuse with "the work is moving".
    if unit_state:
        row["unit_state"] = unit_state
    if state_reason:
        row["state_reason"] = state_reason
    if stalled_for_seconds:
        row["stalled_for_seconds"] = stalled_for_seconds
    return row


def _model_label(model: str, reasoning_effort: str) -> str:
    return " ".join(part for part in (str(model or ""), str(reasoning_effort or "")) if part) or _MODEL_DEFAULT_LABEL


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip()
    return status if status in _STATUS_VOCABULARY else "prepared_not_observed"


def _unmapped_status_source(value: Any) -> str:
    """The status word `_normalize_status` discarded, or "" when it kept it.

    Mirrors `omh.coding.status_board.unmapped_status_source`. That one runs the
    full chat-progress sanitizer, which this file cannot import; a status is an
    identifier-shaped word, so collapsing whitespace and bounding it agrees with
    the sanitizer on every value a status field can hold. Gated by the parity
    table in `tests/test_coding_status_board.py`.
    """
    status = str(value or "").strip()
    if not status or status in _STATUS_VOCABULARY:
        return ""
    collapsed = " ".join(status.split())
    if len(collapsed) <= _STATUS_SOURCE_LIMIT:
        return collapsed
    return collapsed[: _STATUS_SOURCE_LIMIT - 3] + "..."


# Hand-mirror of `omh.evidence.labels`, which this bundle cannot import. Kept
# byte-identical in behaviour by the parity test in
# `tests/test_coding_status_board.py`; the wire values themselves are unchanged
# on both sides.
_CONFIDENCE_BY_VALUE: dict[str, str] = {
    "routing_not_execution": "not run",
    "prepared_not_observed": "not run",
    "observed_partial": "partly seen",
    "observed_reportable": "seen",
    "running": "running",
    "completed": "reported done",
    "failed": "failed",
    "worktree_failed": "failed",
}
_PHASE_BY_VALUE: dict[str, str] = {
    "routing_not_execution": "Route",
    "prepared_not_observed": "Plan",
    "worktree_failed": "Setup",
}
_BOARD_PHASE = "Code"
_LABEL_SEPARATOR = " \u00b7 "


def _status_label(value: str) -> str:
    """`Code \u00b7 running` -- mirrors `omh.evidence.labels.status_label`.

    Fails closed to `not run` for the same reason `normalize_status` does: an
    unrecognized state must never render as work that happened.
    """
    key = str(value or "").strip()
    confidence = _CONFIDENCE_BY_VALUE.get(key, "not run")
    phase = _PHASE_BY_VALUE.get(key, _BOARD_PHASE)
    return f"{phase}{_LABEL_SEPARATOR}{confidence}"


def _status_text(unit: dict[str, Any]) -> str:
    """The status a person reads, with any refused source word attached.

    A stuck `unit_state` replaces the cell outright, for the reason spelled
    out on the surface this mirrors: `running` only ever meant "a process was
    spawned", and it must never render over a unit whose work stopped moving.

    Mirrors `omh.coding.status_board.status_text_for`.
    """
    stuck = _stuck_state_text(unit)
    if stuck:
        return stuck
    status = _status_label(str(unit.get("status", "") or "unknown"))
    source = str(unit.get("unmapped_source_status", "") or "")
    return f"{status} (reported {source})" if source else status


# Hand-mirror of `omh.coding.unit_execution_state.UNIT_STUCK_STATES`, which
# this bundle cannot import. Every state where the process may well be alive
# and the work is still not moving; parity gated in
# `tests/test_coding_status_board.py`.
_STUCK_STATES: Final[frozenset[str]] = frozenset(
    {
        "awaiting_input",
        "permission_blocked",
        "account_limit",
        "data_missing",
        "progress_stalled",
    }
)


def _stuck_state_text(unit: dict[str, Any]) -> str:
    """Mirrors `omh.coding.status_board.stuck_state_text`."""
    state = str(unit.get("unit_state", "") or "")
    if state not in _STUCK_STATES:
        return ""
    parts: list[str] = []
    reason = str(unit.get("state_reason", "") or "")
    if reason:
        parts.append(reason)
    elapsed = str(unit.get("stalled_for_seconds", "") or "")
    if elapsed.isdigit() and int(elapsed) > 0:
        parts.append(f"{elapsed}s since new output")
    return f"{state} ({', '.join(parts)})" if parts else state


def _sort_key(unit: dict[str, Any]) -> tuple[int, str, str]:
    running_first = 0 if unit.get("status") == "running" else 1
    return (running_first, str(unit.get("label", "")), str(unit.get("unit_id", "")))


def _home_dir(omh_home: str | Path | None) -> Path:
    return _expand_path(omh_home) if omh_home else runtime_paths.default_omh_home()


def _expand_path(value: str | Path) -> Path:
    """Expand and resolve, but never raise on a hostile path.

    `Path.resolve()` raises RuntimeError -- NOT OSError -- when it walks a
    symlink loop, so the narrow `(OSError, ValueError)` guards elsewhere in this
    module did not cover it and a looped OMH home crashed `pre_llm_call`
    outright. An unreadable home must be CLASSIFIED, which is the contract
    `tests/test_runtime_reader_filesystem_faults.py` already pins for the
    runtime reader. Falling back to the unresolved path lets the normal
    per-directory listing report `unreadable` instead of taking the hook down.
    """
    expanded = Path(os.path.expandvars(str(value))).expanduser()
    try:
        return expanded.resolve()
    except (OSError, RuntimeError):
        return expanded


def _context_budget_ledger_path(omh_home: str | Path | None) -> Path:
    return _home_dir(omh_home) / "runtime" / _CONTEXT_BUDGET_LEDGER_NAME


def _read_context_budget_ledger(path: Path) -> dict[str, Any]:
    payload, status = _read_json_object_result(path)
    return payload if status == "present" and payload is not None else {}


@contextmanager
def _context_budget_ledger_lock(path: Path) -> Iterator[None]:
    """Hold the same cross-process sidecar lock as core's `locked_json_update`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        mechanism = _acquire_context_budget_lock(handle, lock_path)
        try:
            yield
        finally:
            _release_context_budget_lock(handle, mechanism)


def _acquire_context_budget_lock(handle: Any, lock_path: Path) -> str:
    deadline = time.monotonic() + _CONTEXT_BUDGET_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return "fcntl"
            if msvcrt is None:
                return "none"
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return "msvcrt"
        except OSError as exc:
            if exc.errno not in _LOCK_BUSY_ERRNOS:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for context budget lock: {lock_path}") from exc
            time.sleep(_CONTEXT_BUDGET_LOCK_POLL_INTERVAL)


def _release_context_budget_lock(handle: Any, mechanism: str) -> None:
    if mechanism == "fcntl":
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    elif mechanism == "msvcrt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _safe_int(value: Any) -> int:
    return max(0, int(value)) if isinstance(value, int) and not isinstance(value, bool) else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json_best_effort(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
        with tmp.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp.replace(path)
    except (OSError, ValueError, TypeError):
        return
