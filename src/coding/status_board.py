"""Live coding status board projection and renderer (`omh_coding_status_board/v1`).

Answers one question — "what coding work is running right now?" — by merging
three local observation sources into one row per unit and rendering them as an
aligned, dialect-neutral board. Every row carries a label, the runtime that
owns it, the model that runtime was told to use, a status, an elapsed time, and
a token total.

Boundaries, in order of importance:

- Honesty over completeness. Runtime and model are always exact when present
  because omh itself selected them and put them on the command line. Tokens,
  session refs, and the elapsed time of an unfinished unit are observed or the
  literal `unknown` — never estimated, never derived from a conversation token
  budget (that budget belongs to a different actor and using it here would be a
  category error). A number on the board is a number an executor reported.
- Reporting only. Nothing here is persisted, dispatched, or fed back into a
  route; `build_status_board` reads local artifacts and returns a payload.
  The board is observed activity, not result, verification, review, CI,
  merge-readiness, or merge evidence.
- Deterministic. `now` is a parameter so callers and tests pin it; the clock is
  read only when the caller declines to name a time. Ordering, column widths,
  and truncation are functions of the data alone.
- English by default. Localized copy is opt-in through the explicit `locale`
  argument (fed by `--language` / `OMH_LANG`); the OS locale is never consulted.
- Metadata only. Unit ids, run refs, model ids, and status words are read;
  free-text summaries pass the shared progress sanitizer before they render.

Telemetry parsing is deliberately absent: `unit_telemetry.parse_unit_telemetry`
runs at dispatch time and its values arrive here already persisted in the
dispatch summary, so this module never re-parses executor output.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping

from ..local_store import read_json_object_result, utc_now
from ..evidence import PHASE_CODE, status_label
from ..paths import OmhPaths
from .context_safety import sanitize_user_facing_progress_text
from .executor_progress import project_active_executor_status
from .inflight import read_inflight_markers
from .routing_observation import (
    authenticate_executor_observation,
    build_routing_observation,
    render_routing_status_rows,
)
from .work_reporting import _korean_locale

CODING_STATUS_BOARD_SCHEMA_VERSION: Final[str] = "omh_coding_status_board/v1"

CODING_STATUS_BOARD_CLAIM_BOUNDARY: Final[str] = (
    "Status board rows are metadata-only observed activity. Runtime and model are exact because "
    "omh selected them; tokens, session refs, and the elapsed time of an unfinished unit are "
    "observed or the literal unknown, never estimated. It is not result, verification, review, "
    "CI, merge-readiness, or merge evidence."
)

# The messenger line. The full boundary above is 308 characters against a
# two-row board of roughly 275 -- 53% of what a person sees on a phone would be
# boilerplate they scroll past to reach two lines of data, which is exactly the
# saturation a chat surface has to avoid. The full text stays in the payload and
# in `--json`, where an auditor reads it; the short form carries the two claims
# a reader of the board actually needs.
CODING_STATUS_BOARD_SHORT_BOUNDARY: Final[str] = (
    "Observed activity only; unknown is never estimated."
)

# Closed status vocabulary. Anything else an artifact carries collapses to
# `prepared_not_observed`, which is the honest reading of "we wrote it down but
# never watched it run".
STATUS_VOCABULARY: Final[tuple[str, ...]] = (
    "running",
    "completed",
    "failed",
    "worktree_failed",
    "prepared_not_observed",
)

UNKNOWN: Final[str] = "unknown"
DEFAULT_LIMIT: Final[int] = 20

SOURCE_INFLIGHT: Final[str] = "inflight_markers"
SOURCE_DISPATCH_SUMMARY: Final[str] = "dispatch_summary"
SOURCE_EXECUTOR_PROGRESS: Final[str] = "executor_progress"
# Merge order is also precedence order: an in-flight marker wins over a
# dispatch-summary row for the same unit, and both win over a progress binding.
SOURCE_ORDER: Final[tuple[str, ...]] = (
    SOURCE_INFLIGHT,
    SOURCE_DISPATCH_SUMMARY,
    SOURCE_EXECUTOR_PROGRESS,
)

_SUMMARY_LIMIT: Final[int] = 120
# Bound for a status word the closed vocabulary refused. It is a word, not a
# message. It reaches the STATUS column too: a payload-only field answers an
# auditor reading `--json` and nobody reading the board, and the board is where
# the collapse is actually noticed.
_STATUS_SOURCE_LIMIT: Final[int] = 80
_MODEL_DEFAULT_LABEL: Final[str] = "executor default"
# `inflight.INFLIGHT_MARKER_STATUSES` value that means the marker was read and
# carries observed fields; the other two mean it carries nothing.
_MARKER_PRESENT: Final[str] = "present"

# Column headers, in the same order `omh coding fanout brief` prints its parts.
# `_fanout_brief_unit_line` in src/commands/coding.py joins:
#     unit_id — owner (model_label) — status — elapsed — tokens — session … — summary
# and builds `model_label` with `model_label_for` below, so the board and the
# brief read identically by construction.
_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("LABEL", "label"),
    ("RUNTIME", "runtime"),
    ("MODEL", "model_label"),
    ("STATUS", "status"),
    ("ELAPSED", "elapsed_text"),
    ("TOKENS", "tokens_text"),
    ("SESSION", "session_ref"),
)

_RICH_MARKDOWN: Final[str] = "rich_markdown"
_LIMITED_MARKDOWN: Final[str] = "limited_markdown"


def build_status_board(paths: OmhPaths, *, limit: int = DEFAULT_LIMIT, now: str = "") -> dict[str, Any]:
    """Project every locally observed coding unit into one board payload."""
    observed_at = now or utc_now()
    effective_limit = limit if limit > 0 else 0

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    sources_used: list[str] = []

    for unit in _inflight_units(paths, observed_at):
        _merge_unit(merged, unit, source=SOURCE_INFLIGHT, sources_used=sources_used)
    for unit in _dispatch_summary_units(paths):
        _merge_unit(merged, unit, source=SOURCE_DISPATCH_SUMMARY, sources_used=sources_used)
    for unit in _progress_units(paths, observed_at):
        _merge_unit(merged, unit, source=SOURCE_EXECUTOR_PROGRESS, sources_used=sources_used)

    units = sorted(merged.values(), key=_board_sort_key)
    running_count = sum(1 for unit in units if unit["status"] == "running")
    return {
        "schema_version": CODING_STATUS_BOARD_SCHEMA_VERSION,
        "observed_at": observed_at,
        "unit_count": len(units),
        "running_count": running_count,
        "units": units[:effective_limit],
        "sources_used": [source for source in SOURCE_ORDER if source in sources_used],
        "claim_boundary": CODING_STATUS_BOARD_CLAIM_BOUNDARY,
    }


def render_status_board_text(payload: dict[str, Any], *, locale: str = "") -> str:
    """Aligned ASCII board. English unless `locale` explicitly names Korean."""
    korean = _korean_locale(locale)
    units = _payload_units(payload)
    lines = [_header_line(payload, korean=korean)]
    if not units:
        lines.append(_empty_line(korean=korean))
        lines.append(str(payload.get("claim_boundary", "")))
        return "\n".join(line for line in lines if line)

    widths = _column_widths(units)
    lines.append(_table_row([header for header, _ in _COLUMNS], widths, summary=""))
    for unit in units:
        cells = [_cell(unit, field) for _, field in _COLUMNS]
        lines.append(_table_row(cells, widths, summary=str(unit.get("summary", "") or "")))
        observation = unit.get("routing_observation")
        if isinstance(observation, Mapping):
            lines.extend(render_routing_status_rows(observation))
    truncation = _truncation_line(payload, korean=korean)
    if truncation:
        lines.append(truncation)
    lines.append(str(payload.get("claim_boundary", "")))
    return "\n".join(line for line in lines if line)


def status_board_messenger_body(payload: dict[str, Any], *, render_profile: str = _LIMITED_MARKDOWN) -> str:
    """Messenger-safe body. `rich_markdown` keeps alignment; `limited_markdown` is flat bullets.

    The boundary is the SHORT form and sits OUTSIDE the fence. Inside it, a
    paragraph of prose is monospace-wrapped at the table's width, which reads as
    broken rendering rather than as a caveat; and at full length it was more of
    the message than the data was.
    """
    if render_profile == _RICH_MARKDOWN:
        return (
            "```\n"
            + _aligned_rows_only(payload)
            + "\n```\n"
            + CODING_STATUS_BOARD_SHORT_BOUNDARY
        )
    units = _payload_units(payload)
    lines = [_header_line(payload, korean=False)]
    if not units:
        lines.append(_empty_line(korean=False))
    for unit in units:
        lines.append(_bullet_line(unit))
    truncation = _truncation_line(payload, korean=False)
    if truncation:
        lines.append(truncation)
    lines.append(CODING_STATUS_BOARD_SHORT_BOUNDARY)
    return "\n".join(line for line in lines if line)


def _aligned_rows_only(payload: dict[str, Any]) -> str:
    """The aligned table without the trailing boundary paragraph."""
    boundary = str(payload.get("claim_boundary", "") or "")
    text = render_status_board_text(payload)
    if boundary and text.endswith(boundary):
        text = text[: -len(boundary)]
    return text.rstrip("\n")


def model_label_for(model: str, reasoning_effort: str) -> str:
    """The `gpt-5.6-sol xhigh` label shape shared with `omh coding fanout brief`."""
    return " ".join(part for part in (str(model or ""), str(reasoning_effort or "")) if part) or _MODEL_DEFAULT_LABEL


def elapsed_text_for(elapsed_seconds: Any) -> str:
    """Compact human elapsed form: `45s`, `35m`, `2h 5m`, `1d 1h`, or `unknown`."""
    if not isinstance(elapsed_seconds, int) or isinstance(elapsed_seconds, bool) or elapsed_seconds < 0:
        return UNKNOWN
    if elapsed_seconds < 60:
        return f"{elapsed_seconds}s"
    if elapsed_seconds < 3600:
        return f"{elapsed_seconds // 60}m"
    if elapsed_seconds < 86400:
        hours, minutes = divmod(elapsed_seconds // 60, 60)
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(elapsed_seconds // 3600, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def tokens_text_for(tokens_total: Any) -> str:
    """Thousands-separated observed total, or the literal `unknown`."""
    if isinstance(tokens_total, int) and not isinstance(tokens_total, bool) and tokens_total >= 0:
        return f"{tokens_total:,}"
    return UNKNOWN


def normalize_status(value: Any) -> str:
    status = str(value or "").strip()
    return status if status in STATUS_VOCABULARY else "prepared_not_observed"


def unmapped_status_source(value: Any) -> str:
    """The status word `normalize_status` discarded, or "" when it kept it.

    The downgrade itself is correct and stays: an unknown status word must not
    be read as an observation, and `prepared_not_observed` is the honest floor.
    What was wrong is that the word then vanished, so a board could not
    distinguish "nothing was ever written down" from "an executor reported
    something this vocabulary does not know". A row carries the discarded word
    beside the downgraded status instead of losing it.
    """
    status = str(value or "").strip()
    if not status or status in STATUS_VOCABULARY:
        return ""
    return sanitize_user_facing_progress_text(status, max_chars=_STATUS_SOURCE_LIMIT)


def status_text_for(unit: Mapping[str, Any]) -> str:
    """The STATUS column as a person reads it: the vocabulary word, plus what was refused.

    `prepared_not_observed` alone cannot distinguish "nobody ever watched this
    run" from "an executor said something this vocabulary does not know", and
    those call for different actions. The refused word rides in parentheses on
    the same cell rather than in a column of its own, so a board with nothing
    refused is byte-identical to the one this repo already renders.

    Hand-mirrored by `plugin_bundle/omh/status_board_reader._status_text`, which
    cannot import this module; `tests/test_coding_status_board.py` gates the two
    against each other.
    """
    # Every row on this board is a coding unit, so `Code` is the phase when the
    # value does not imply a more specific one (`worktree_failed` implies
    # `Setup`). The wire value stays in `unit["status"]` for anything parsing
    # the payload; only this cell changes.
    status = status_label(str(unit.get("status", "") or UNKNOWN), default_phase=PHASE_CODE)
    source = str(unit.get("unmapped_source_status", "") or "")
    return f"{status} (reported {source})" if source else status


def _merge_unit(
    merged: dict[tuple[str, str], dict[str, Any]],
    unit: dict[str, Any],
    *,
    source: str,
    sources_used: list[str],
) -> None:
    key = (str(unit.get("fanout_id", "")), str(unit.get("unit_id", "")))
    if source not in sources_used:
        sources_used.append(source)
    if key in merged:
        return
    merged[key] = {field: value for field, value in unit.items() if field != "fanout_id"}


def _board_sort_key(unit: dict[str, Any]) -> tuple[int, str, str]:
    running_first = 0 if unit.get("status") == "running" else 1
    return (running_first, str(unit.get("label", "")), str(unit.get("unit_id", "")))


def _inflight_units(paths: OmhPaths, observed_at: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for marker in read_inflight_markers(paths):
        if not isinstance(marker, dict):
            continue
        unit_id = str(marker.get("unit_id", "") or "")
        if not unit_id:
            continue
        # `absent` and `unreadable` markers carry no observed fields at all.
        # Rendering one as a running unit would put a row on the board that
        # nothing observed, so they are dropped rather than shown as unknown.
        if str(marker.get("marker_status", _MARKER_PRESENT)) != _MARKER_PRESENT:
            continue
        elapsed = _elapsed_since(str(marker.get("started_at", "") or ""), observed_at)
        units.append(
            _unit_row(
                fanout_id=str(marker.get("fanout_id", "") or ""),
                unit_id=unit_id,
                label=unit_id,
                run_ref=str(marker.get("run_ref", "") or ""),
                runtime=str(marker.get("owner", "") or ""),
                runtime_host=str(marker.get("owner_host", "") or ""),
                model=str(marker.get("model", "") or ""),
                reasoning_effort=str(marker.get("reasoning_effort", "") or ""),
                status="running",
                elapsed_seconds=elapsed,
                # A running unit has reported no total yet. Anything we put here
                # would be a guess, so it stays unknown until an executor says.
                tokens_total=UNKNOWN,
                session_ref="",
                # A marker records where the unit runs, not what it has done.
                # The worktree path is deliberately not shown: it is a local
                # filesystem path, not observed progress.
                summary="",
            )
        )
    return units


def _dispatch_summary_units(paths: OmhPaths) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    root = paths.fanout_contracts_dir
    if not root.is_dir():
        return units
    for fanout_dir in sorted(root.iterdir()):
        if not fanout_dir.is_dir() or fanout_dir.is_symlink():
            continue
        summary, error = read_json_object_result(fanout_dir / "dispatch_summary.json")
        if error or not isinstance(summary, dict):
            continue
        fanout_id = str(summary.get("fanout_id", "") or fanout_dir.name)
        contract_units = _contract_units(fanout_dir)
        for entry in summary.get("units", []):
            if not isinstance(entry, dict):
                continue
            unit_id = str(entry.get("unit_id", "") or "")
            if not unit_id:
                continue
            contract_unit = contract_units.get(unit_id, {})
            handoff = contract_unit.get("handoff") if isinstance(contract_unit.get("handoff"), Mapping) else {}
            route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else {}
            observation = build_routing_observation(
                route=route,
                session_observation=authenticate_executor_observation({
                    "status": entry.get("status"),
                    "owner": entry.get("owner"),
                    "model": entry.get("model"),
                    "reasoning_effort": entry.get("reasoning_effort"),
                    "elapsed_seconds": _finished_seconds(entry.get("duration_seconds")),
                    "tokens": _reported_tokens(entry),
                    "session_id": entry.get("session_ref"),
                    "run_id": entry.get("run_ref"),
                }),
            )
            units.append(
                _unit_row(
                    fanout_id=fanout_id,
                    unit_id=unit_id,
                    label=str(contract_unit.get("title", "") or unit_id),
                    run_ref=str(entry.get("run_ref", "") or ""),
                    runtime=str(entry.get("owner", "") or ""),
                    runtime_host="",
                    model=str(entry.get("model", "") or ""),
                    reasoning_effort=str(entry.get("reasoning_effort", "") or ""),
                    status=normalize_status(entry.get("status")),
                    unmapped_source_status=unmapped_status_source(entry.get("status")),
                    elapsed_seconds=_finished_seconds(entry.get("duration_seconds")),
                    tokens_total=_reported_tokens(entry),
                    session_ref=str(entry.get("session_ref", "") or ""),
                    summary=str(entry.get("reason", "") or ""),
                    routing_observation=observation,
                )
            )
    return units


def _progress_units(paths: OmhPaths, observed_at: str) -> list[dict[str, Any]]:
    projection = project_active_executor_status(paths, now=observed_at)
    units: list[dict[str, Any]] = []
    for row in projection.get("active_executors", []):
        if not isinstance(row, dict):
            continue
        unit_id = str(row.get("target_id", "") or "")
        if not unit_id:
            continue
        event = row.get("latest_event", {})
        event = event if isinstance(event, dict) else {}
        observation = build_routing_observation(
            session_observation=authenticate_executor_observation({
                **row,
                **event,
                "status": event.get("status") or row.get("state"),
                "owner": row.get("executor_profile"),
                "run_id": row.get("target_id"),
            }),
        )
        units.append(
            _unit_row(
                fanout_id="",
                unit_id=unit_id,
                label=unit_id,
                run_ref=unit_id if str(row.get("target_type", "")) == "run" else "",
                runtime=str(row.get("executor_profile", "") or ""),
                runtime_host="",
                # A progress binding records who is working, not which model was
                # picked; the route lives in the fanout contract, so the board
                # says unknown rather than inventing one.
                model="",
                reasoning_effort="",
                status="running",
                elapsed_seconds=_elapsed_since(str(row.get("latest_observed_at", "") or ""), observed_at),
                tokens_total=UNKNOWN,
                session_ref="",
                summary=str(event.get("summary", "") or ""),
                routing_observation=observation,
            )
        )
    return units


def _unit_row(
    *,
    fanout_id: str,
    unit_id: str,
    label: str,
    run_ref: str,
    runtime: str,
    runtime_host: str,
    model: str,
    reasoning_effort: str,
    status: str,
    elapsed_seconds: Any,
    tokens_total: Any,
    session_ref: str,
    summary: str,
    unmapped_source_status: str = "",
    routing_observation: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    row = {
        "fanout_id": fanout_id,
        "label": label or unit_id or UNKNOWN,
        "unit_id": unit_id,
        "run_ref": run_ref or UNKNOWN,
        "runtime": runtime or UNKNOWN,
        "runtime_host": runtime_host or UNKNOWN,
        "model": model or UNKNOWN,
        "reasoning_effort": reasoning_effort or UNKNOWN,
        "model_label": model_label_for(model, reasoning_effort),
        "status": status,
        "elapsed_seconds": elapsed_seconds if isinstance(elapsed_seconds, int) else UNKNOWN,
        "elapsed_text": elapsed_text_for(elapsed_seconds),
        "tokens_total": tokens_total if isinstance(tokens_total, int) else UNKNOWN,
        "tokens_text": tokens_text_for(tokens_total),
        "session_ref": session_ref or UNKNOWN,
        "summary": sanitize_user_facing_progress_text(summary, max_chars=_SUMMARY_LIMIT),
    }
    # Absent unless a word was actually discarded, so an absent key means the
    # status was accepted verbatim -- never that nothing was checked.
    if unmapped_source_status:
        row["unmapped_source_status"] = unmapped_source_status
    if routing_observation is not None:
        row["routing_observation"] = dict(routing_observation)
        row["routing_status_rows"] = list(render_routing_status_rows(routing_observation))
    return row


def _contract_units(fanout_dir: Path) -> dict[str, dict[str, Any]]:
    contract, error = read_json_object_result(fanout_dir / "fanout_contract.json")
    if error or not isinstance(contract, dict):
        return {}
    units: dict[str, dict[str, Any]] = {}
    for unit in contract.get("units", []):
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id", "") or "")
        if unit_id:
            units[unit_id] = unit
    return units


def _unit_titles(fanout_dir: Path) -> dict[str, str]:
    """Compatibility helper retained for plugin-parity tests."""
    return {
        unit_id: str(unit.get("title", "") or unit_id)
        for unit_id, unit in _contract_units(fanout_dir).items()
    }


def _finished_seconds(value: Any) -> Any:
    """Observed wall time of a finished unit, floored to whole seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNKNOWN
    if value < 0:
        return UNKNOWN
    return int(value)


def _observed_tokens(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return UNKNOWN
    return value


def _reported_tokens(entry: Mapping[str, Any]) -> Any:
    """Prefer a provider-stated total, else the sum of stated components.

    Neither codex nor claude reports a `total_tokens`, verified against real
    captured output, so reading only `tokens_total` left this column `unknown`
    on every actual run -- the exact defect the board exists to remove.
    `tokens_billable` is the sum of components the CLI itself printed
    (input, output, cache read, cache write, reasoning); it is aggregation of
    stated numbers, never an estimate, and it carries its own
    `tokens_billable_source` label in the record for anyone auditing it.
    """
    total = _observed_tokens(entry.get("tokens_total"))
    if total != UNKNOWN:
        return total
    return _observed_tokens(entry.get("tokens_billable"))


def _elapsed_since(started_at: str, observed_at: str) -> Any:
    """Whole seconds between two observed timestamps, or `unknown` if either is not one."""
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(observed_at)
    if start is None or end is None:
        return UNKNOWN
    seconds = int((end - start).total_seconds())
    return seconds if seconds >= 0 else UNKNOWN


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _payload_units(payload: dict[str, Any]) -> list[dict[str, Any]]:
    units = payload.get("units", [])
    return [unit for unit in units if isinstance(unit, dict)] if isinstance(units, list) else []


def _cell(unit: dict[str, Any], field: str) -> str:
    # The STATUS column is the one cell that is not a plain field read: it
    # carries the refused source word when there was one. Doing it here rather
    # than as a precomputed row field keeps `_column_widths`, the aligned table,
    # and the fenced messenger profile in agreement by construction.
    if field == "status":
        return status_text_for(unit)
    return str(unit.get(field, "") or UNKNOWN)


def _column_widths(units: list[dict[str, Any]]) -> list[int]:
    return [
        max([len(header)] + [len(_cell(unit, field)) for unit in units])
        for header, field in _COLUMNS
    ]


def _table_row(cells: list[str], widths: list[int], *, summary: str) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths)]
    row = "  ".join(padded).rstrip()
    return f"{row}  {summary}".rstrip() if summary else row


def _bullet_line(unit: dict[str, Any]) -> str:
    elapsed_text = str(unit.get("elapsed_text", UNKNOWN) or UNKNOWN)
    elapsed_phrase = "elapsed unknown" if elapsed_text == UNKNOWN else elapsed_text
    tokens_text = str(unit.get("tokens_text", UNKNOWN) or UNKNOWN)
    tokens_phrase = "tokens unknown" if tokens_text == UNKNOWN else f"{tokens_text} tokens"
    parts = [
        str(unit.get("label", "")),
        # Runtime and model are ONE field visually: "codex (gpt-5.6-sol xhigh)".
        # Separating them with a dash as well produced "codex — (gpt-5.6-sol
        # xhigh)", a doubled separator around a parenthetical.
        f"{unit.get('runtime', UNKNOWN)} ({unit.get('model_label', _MODEL_DEFAULT_LABEL)})",
        status_text_for(unit),
        elapsed_phrase,
        tokens_phrase,
        f"session {unit.get('session_ref', UNKNOWN)}",
    ]
    line = "- " + " — ".join(parts)
    summary = str(unit.get("summary", "") or "")
    return f"{line} — {summary}" if summary else line


def _header_line(payload: dict[str, Any], *, korean: bool) -> str:
    running = int(payload.get("running_count", 0) or 0)
    total = int(payload.get("unit_count", 0) or 0)
    observed_at = str(payload.get("observed_at", "") or UNKNOWN)
    if korean:
        return f"코딩 작업 현황 (실행 중 {running} / 전체 {total}) — 관측 시각 {observed_at}"
    return f"Coding status board ({running} running of {total} observed) — observed at {observed_at}"


def _empty_line(*, korean: bool) -> str:
    if korean:
        return "관측된 코딩 작업이 없습니다."
    return "No coding work observed."


def _truncation_line(payload: dict[str, Any], *, korean: bool) -> str:
    total = int(payload.get("unit_count", 0) or 0)
    shown = len(_payload_units(payload))
    dropped = total - shown
    if dropped <= 0:
        return ""
    if korean:
        return f"{shown}개만 표시했습니다. {dropped}개는 표시 한도로 생략되었습니다."
    return f"Showing {shown} of {total} units; {dropped} not shown because of the display limit."
