"""Localized end-of-run summary from observed host accounting.

The owner's contract for a finished ultrawork run is a closing block like::

    소요 시간: 2,741초
    토큰 사용량: 4,849,639
    사용 모델: gpt-5.6-sol, glm-5.2-ultrafast

with the numbers coming from Hermes' own session accounting in
``state.db`` — never estimated by the model, which cannot know its own
token usage. The tool reads the calling session's row plus its
``delegate_task`` children (one level, matched via ``parent_session_id``)
read-only, and renders the lines in the requested language.
"""
from __future__ import annotations

from .. import runtime_paths

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

RUN_SUMMARY_CLAIM_BOUNDARY = (
    "Observed host accounting from state.db (session row plus direct "
    "delegate_task children). Token totals are input+output tokens as Hermes "
    "recorded them; this is not billing-exact provider evidence."
)

# Labels only — numbers are always rendered with thousands separators. The
# elapsed placeholder carries its own unit suffix (see _ELAPSED_UNITS) so an
# unmeasured elapsed time can render the bare word "unknown" instead of
# "unknowns" / "unknown초".
_SUMMARY_LABELS: dict[str, tuple[str, str, str]] = {
    "en": ("Elapsed time: {elapsed}", "Tokens used: {tokens}", "Models used: {models}"),
    "ko": ("소요 시간: {elapsed}", "토큰 사용량: {tokens}", "사용 모델: {models}"),
    "ja": ("所要時間: {elapsed}", "トークン使用量: {tokens}", "使用モデル: {models}"),
    "zh": ("耗时: {elapsed}", "Token 使用量: {tokens}", "使用模型: {models}"),
}

# Unit suffix appended to a *measured* elapsed value only. Left in English
# ("unknown") when the value is unmeasured, matching the sentinel word used
# elsewhere in OMH's status renderers (e.g. `src/coding/status_board.py`).
_ELAPSED_UNITS: dict[str, str] = {"en": "s", "ko": "초", "ja": "秒", "zh": "秒"}
_ELAPSED_UNKNOWN: str = "unknown"

OMH_RUN_SUMMARY_SCHEMA = {
    "name": "omh_run_summary",
    "description": (
        "Render the localized end-of-run summary (elapsed seconds and token "
        "usage) from Hermes' own session accounting — the calling session plus "
        "its delegate_task children. Call it once when a workflow run (e.g. "
        "ulw-work) completes, pass the language the conversation is in, and "
        "print summary_text verbatim as the closing lines. Never estimate "
        "these numbers yourself."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "enum": sorted(_SUMMARY_LABELS),
                "description": (
                    "Language for the summary labels (explicit caller choice; "
                    "defaults to en)."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional session id override; defaults to the calling "
                    "session the host reports."
                ),
            },
            "hermes_home": {
                "type": "string",
                "description": "Optional HERMES_HOME override. Defaults to ~/.hermes.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def _default_hermes_home() -> Path:
    return runtime_paths.default_hermes_home()


def _rows(
    state_db: Path, session_id: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    try:
        connection = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=0.25)
    except sqlite3.Error:
        return None, [], []
    try:
        connection.row_factory = sqlite3.Row
        columns = (
            "id, model, started_at, ended_at, input_tokens, output_tokens, "
            "cache_read_tokens, reasoning_tokens, api_call_count, "
            "actual_cost_usd, estimated_cost_usd"
        )
        session = connection.execute(
            f"SELECT {columns} FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        children = connection.execute(
            f"SELECT {columns} FROM sessions WHERE parent_session_id = ?", (session_id,)
        ).fetchall()
        scope_ids = [session_id, *(row["id"] for row in children)]
        models: list[str] = []
        try:
            placeholders = ",".join("?" for _ in scope_ids)
            usage_rows = connection.execute(
                "SELECT model, MIN(first_seen) AS seen FROM session_model_usage "
                f"WHERE session_id IN ({placeholders}) GROUP BY model ORDER BY seen",
                scope_ids,
            ).fetchall()
            models = [str(row["model"]) for row in usage_rows if row["model"]]
        except sqlite3.Error:
            models = []
        if not models:
            # Older hosts without the usage table still record the session's
            # bound model on the row itself.
            seen: list[str] = []
            for row in (session, *children):
                model = str(row["model"] or "") if row is not None else ""
                if model and model not in seen:
                    seen.append(model)
            models = seen
        return (
            dict(session) if session else None,
            [dict(row) for row in children],
            models,
        )
    except sqlite3.Error:
        return None, [], []
    finally:
        connection.close()


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _optional_number(value: Any) -> float | None:
    """Like `_number`, but preserves "never recorded" as `None`.

    `started_at` is the one field in this row that can genuinely be absent
    (a session row without a start time was never observed starting).
    Collapsing that into `0.0` — as `_number` deliberately does for token and
    cost columns, which really do default to zero — would make an unmeasured
    elapsed time indistinguishable from a run that took no time at all.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def omh_run_summary_handler(args: dict[str, Any], **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_run_summary", args, kwargs)
    language = str(args.get("language", "") or "en").strip().lower()
    if language not in _SUMMARY_LABELS:
        language = "en"
    session_id = str(args.get("session_id", "") or "") or str(kwargs.get("session_id", "") or "")
    home = runtime_paths.plugin_home(args.get("hermes_home"), hermes=True)

    payload: dict[str, Any] = {
        "schema_version": "omh_run_summary/v1",
        "language": language,
        "claim_boundary": RUN_SUMMARY_CLAIM_BOUNDARY,
    }
    if not session_id:
        payload["status"] = "no_session"
        payload["error"] = (
            "the host did not supply a session id and none was passed; "
            "run summaries need the session's accounting row"
        )
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    session, children, models = _rows(home / "state.db", session_id)
    if session is None:
        payload["status"] = "not_observed"
        payload["error"] = f"no session row observed for {session_id!r}"
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    started = _optional_number(session.get("started_at"))
    ended_raw = _optional_number(session.get("ended_at"))
    ended = ended_raw if ended_raw is not None else time.time()
    # A session row with no recorded start time never observed starting: an
    # honest "unknown" beats a fabricated 0s that would read as a run that
    # took no time at all.
    elapsed: int | None = max(0, int(round(ended - started))) if started is not None else None
    scope = [session, *children]
    input_tokens = int(sum(_number(row.get("input_tokens")) for row in scope))
    output_tokens = int(sum(_number(row.get("output_tokens")) for row in scope))
    cache_read = int(sum(_number(row.get("cache_read_tokens")) for row in scope))
    reasoning = int(sum(_number(row.get("reasoning_tokens")) for row in scope))
    tokens_used = input_tokens + output_tokens
    cost = sum(
        _number(row.get("actual_cost_usd")) or _number(row.get("estimated_cost_usd"))
        for row in scope
    )
    elapsed_text = f"{elapsed:,}{_ELAPSED_UNITS[language]}" if elapsed is not None else _ELAPSED_UNKNOWN
    elapsed_line, tokens_line, models_line = _SUMMARY_LABELS[language]
    lines = [
        elapsed_line.format(elapsed=elapsed_text),
        tokens_line.format(tokens=f"{tokens_used:,}"),
    ]
    if models:
        lines.append(models_line.format(models=", ".join(models)))
    payload.update(
        {
            "status": "observed",
            "session_id": session_id,
            "elapsed_seconds": elapsed,
            "tokens_used": tokens_used,
            "models_used": models,
            "breakdown": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "reasoning_tokens": reasoning,
                "api_calls": int(sum(_number(row.get("api_call_count")) for row in scope)),
                "cost_usd": round(cost, 4),
                "subagent_sessions": len(children),
            },
            "summary_text": "\n".join(lines),
        }
    )
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
