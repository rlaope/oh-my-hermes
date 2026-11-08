"""A throwaway OMH home and Hermes home for the delegation ledger, graph and snapshot tests.

`state.db` holds the tables and columns the delegation graph reads, in the
shape Hermes writes them (`hermes_state_common.py`): `sessions` with the
`_delegate_from` marker and reasoning effort in `model_config` and the
`output_tokens` Hermes adds each API call's count to,
`session_model_usage`, `messages`, and `async_delegations` with `task_json`.
The hook payloads are the ones Hermes passes: `subagent_start` and
`subagent_stop` as `tools/delegate_tool.py` and `delegate_tool_results.py`
build them, and `post_tool_call` for `delegate_task` carrying the dispatch
handle `delegate_tool_dispatch.py::_dispatched_payload` returns.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import Iterator
from unittest.mock import patch

PARENT = "20261020_140200_parent"
SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, source TEXT, model TEXT, model_config TEXT, started_at REAL,
    ended_at REAL, end_reason TEXT, parent_session_id TEXT, output_tokens INTEGER DEFAULT 0
);
CREATE TABLE session_model_usage (
    session_id TEXT NOT NULL, model TEXT NOT NULL, billing_provider TEXT NOT NULL DEFAULT '',
    api_call_count INTEGER NOT NULL DEFAULT 0, first_seen REAL, last_seen REAL
);
CREATE TABLE messages (session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT);
CREATE TABLE async_delegations (
    delegation_id TEXT PRIMARY KEY, parent_session_id TEXT, state TEXT, dispatched_at REAL, task_json TEXT
);
"""


class Homes:
    def __init__(self, root: Path) -> None:
        self.omh = root / "omh"
        self.hermes = root / "hermes"
        self.omh.mkdir()
        self.hermes.mkdir()
        connection = sqlite3.connect(self.hermes / "state.db")
        connection.executescript(SCHEMA)
        connection.commit()
        connection.close()

    def execute(self, sql: str, parameters: tuple = ()) -> None:
        connection = sqlite3.connect(self.hermes / "state.db")
        connection.execute(sql, parameters)
        connection.commit()
        connection.close()

    def session(self, session_id: str, model: str, *, parent: str = "", effort: str = "", started: float = 0.0,
                ended: float | None = None, end_reason: str | None = None) -> None:
        config: dict = {}
        if parent:
            config["_delegate_from"] = parent
        if effort:
            config["reasoning_config"] = {"enabled": True, "effort": effort}
        self.execute(
            "INSERT OR REPLACE INTO sessions (id, source, model, model_config, started_at, ended_at, end_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, "subagent" if parent else "discord", model, json.dumps(config), started, ended, end_reason),
        )

    def tokens(self, session_id: str, count: int) -> None:
        """The output tokens a session's row has counted, as Hermes' per-call deltas leave it."""
        self.execute("UPDATE sessions SET output_tokens = ? WHERE id = ?", (count, session_id))

    def rotate(self, old: str, new: str, *, at: float = 0.0) -> None:
        """Hermes' rotating compaction (`publish_compression_child`, `compression.in_place: false`).

        ``old`` is closed with `compression` and ``new`` opens under it with
        the same source, model and `model_config` (the agent's own, so a
        delegate child's continuation keeps its `_delegate_from`), counting
        its tokens from 0.
        """
        self.execute(
            "INSERT INTO sessions (id, source, model, model_config, started_at, parent_session_id) "
            "SELECT ?, source, model, model_config, ?, id FROM sessions WHERE id = ?",
            (new, at, old),
        )
        self.execute("UPDATE sessions SET ended_at = ?, end_reason = 'compression' WHERE id = ?", (at, old))

    def usage(self, session_id: str, model: str, *, last_seen: float) -> None:
        self.execute(
            "INSERT INTO session_model_usage (session_id, model, api_call_count, first_seen, last_seen) "
            "VALUES (?, ?, 1, ?, ?)",
            (session_id, model, last_seen - 1, last_seen),
        )

    def opener(self, session_id: str, text: str) -> None:
        self.execute("INSERT INTO messages (session_id, role, content) VALUES (?, 'user', ?)", (session_id, text))

    def delegation(self, delegation_id: str, goals: list[str], *, model: str | None = None) -> None:
        self.execute(
            "INSERT INTO async_delegations (delegation_id, parent_session_id, state, dispatched_at, task_json) "
            "VALUES (?, ?, 'running', 0, ?)",
            (delegation_id, PARENT, json.dumps({"goals": goals, "model": model})),
        )

    def hooks(self) -> dict:
        return {"omh_home": str(self.omh), "hermes_home": str(self.hermes)}


@contextmanager
def homes() -> Iterator[Homes]:
    """Fresh homes, named to the bundle the way Hermes names them: through the environment."""
    from omh.plugin_bundle.omh import delegation_ledger
    from omh.plugin_bundle.omh.named_owner_choice import reset_turn_owners

    with TemporaryDirectory() as tmp, patch.dict(
        os.environ, {"OMH_HOME": str(Path(tmp) / "omh"), "HERMES_HOME": str(Path(tmp) / "hermes")}
    ):
        delegation_ledger._roots.clear()
        delegation_ledger._titles.clear()
        delegation_ledger._spawned.clear()
        delegation_ledger._spawned_ids.clear()
        reset_turn_owners()  # a coding owner one test's request named is no other test's choice
        yield Homes(Path(tmp))
        delegation_ledger._roots.clear()
        delegation_ledger._titles.clear()
        delegation_ledger._spawned.clear()
        delegation_ledger._spawned_ids.clear()
        reset_turn_owners()


def start(homes: Homes, child: str, subagent_id: str, goal: str, *, parent: str = PARENT, turn: str = "turn-3",
          parent_subagent: str | None = None, now: float) -> bool:
    from omh.plugin_bundle.omh.delegation_ledger import observe_subagent_start

    return observe_subagent_start(
        {"parent_session_id": parent, "parent_turn_id": turn, "parent_subagent_id": parent_subagent,
         "child_session_id": child, "child_subagent_id": subagent_id, "child_role": "leaf", "child_goal": goal,
         **homes.hooks()},
        now=now,
    )


def dispatched(homes: Homes, subagent_ids: list[str], *, delegation_id: str = "deleg-1", session: str = PARENT,
               turn: str = "turn-3", now: float) -> bool:
    from omh.plugin_bundle.omh.delegation_ledger import observe_delegate_call

    result = {"status": "dispatched", "mode": "background", "count": len(subagent_ids),
              "delegation_id": delegation_id, "goals": ["g"] * len(subagent_ids), "subagent_ids": subagent_ids}
    return observe_delegate_call(
        {"tool_name": "delegate_task", "result": json.dumps(result), "session_id": session,
         "tool_call_id": f"call-{delegation_id}", "turn_id": turn, "status": "ok", "duration_ms": 30,
         **homes.hooks()},
        now=now,
    )


def stop(homes: Homes, child: str, status: str = "completed", *, parent: str = PARENT, duration_ms: int = 62_000,
         now: float) -> bool:
    from omh.plugin_bundle.omh.delegation_ledger import observe_subagent_stop

    return observe_subagent_stop(
        {"parent_session_id": parent, "parent_turn_id": "turn-3", "child_session_id": child, "child_role": "leaf",
         "child_summary": "SECRET SUMMARY TEXT", "child_status": status, "tool_call_history": [],
         "duration_ms": duration_ms, **homes.hooks()},
        now=now,
    )


def route(homes: Homes, category: str, model: str, effort: str, *, written_at: float, session: str = PARENT,
          origin: str = "head") -> None:
    from omh.plugin_bundle.omh.hermes_delegation import append_delegation_route_provenance

    append_delegation_route_provenance(
        {"origin": origin, "written_at": written_at, "category": category, "alias": model, "wire_model": model,
         "provider": "anthropic", "reasoning_effort": effort, "from_alias": "", "session_id": session},
        homes.omh,
    )
