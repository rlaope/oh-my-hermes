"""The live Hermes TUI sessions a widget could plausibly be rendering for.

``state.db`` is the host's own record of which sessions exist and which one
the user is in front of. Two HUD readers need the same answer from it:

* the effective-yolo projection (``approval_bypass``), which may only read a
  ``/yolo`` flag off a session a widget is actually rendering, and
* the plan-todo session scope (``runtime_reader._todo_summary``), which must
  not project a previous session's checklist into a new one.

Both scope the question identically -- ``source='tui'``, not ended, archived,
or hidden, not a delegation child, ordered by the host's own MRU column
(``last_activity_at``) -- so the scoping lives here once instead of as two
copies of the same SQL.

An empty result means the question is UNANSWERABLE here: no ``state.db``, an
older schema, an unreadable file, or no live TUI session at all. It is never a
negative answer, and every caller must fall back to what it would have done
without this surface rather than acting on the silence.
"""
from __future__ import annotations

from . import runtime_paths

from pathlib import Path
from typing import Any

# A host restart leaves no live row behind, and nothing re-stamps a row after
# the process that owned it is gone. Six hours bounds how long the freshest
# surviving row may keep speaking for a session someone is looking at; it is
# the same bound the approval-bypass ledger uses, for the same reason.
LIVE_TUI_SESSION_FRESH_SECONDS = 6 * 3600.0
_LIVE_TUI_SESSION_ROW_LIMIT = 32


def live_tui_session_rows(hermes_home: str = "") -> list[dict[str, Any]]:
    """Live TUI session rows, most recently active first.

    Each row carries the host's own ``id``, the raw ``started_at`` and
    ``activity`` stamps, and the parsed ``model_config`` dict. The stamps stay
    raw on purpose: what an unusable timestamp means differs per caller, so
    this reader does not decide it. Rows whose ``model_config`` is unparseable
    or names a delegation parent are dropped, matching the host's own view of
    which sessions a person is driving.
    """
    import json
    import sqlite3
    from urllib.parse import quote

    home = Path(hermes_home).expanduser() if hermes_home else runtime_paths.default_hermes_home()
    path = home / "state.db"
    if not path.exists():
        return []
    try:
        connection = sqlite3.connect(
            f"file:{quote(str(path))}?mode=ro", uri=True, timeout=0.2
        )
    except sqlite3.Error:
        return []
    rows: list[dict[str, Any]] = []
    try:
        cursor = connection.execute(
            """
            SELECT id, model_config, COALESCE(last_activity_at, started_at), started_at
            FROM sessions
            WHERE source = 'tui'
              AND ended_at IS NULL
              AND COALESCE(archived, 0) = 0
              AND COALESCE(hidden, 0) = 0
              AND (
                model_config IS NULL
                OR NOT json_valid(model_config)
                OR json_extract(model_config, '$._delegate_from') IS NULL
              )
            ORDER BY COALESCE(last_activity_at, started_at) DESC
            LIMIT ?
            """,
            (_LIVE_TUI_SESSION_ROW_LIMIT,),
        )
        for session_id, raw_config, activity, started_at in cursor.fetchall():
            try:
                config = json.loads(raw_config) if raw_config else {}
            except (ValueError, TypeError):
                continue
            if not isinstance(config, dict) or config.get("_delegate_from"):
                continue
            rows.append(
                {
                    "id": str(session_id or ""),
                    "model_config": config,
                    "activity": activity,
                    "started_at": started_at,
                }
            )
    except (sqlite3.Error, TypeError, ValueError):
        return []
    finally:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    return rows
