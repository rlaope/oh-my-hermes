"""Producers for the OMH text Hermes can send per request, for `budget_metrics()`.

Three surfaces can reach the model on every turn of a session with OMH
installed, and none of them is the skill body total the older budget watches:

- the skill index lines (`src/skills/skill_index.py`), sent on every request;
- the plugin bundle's registered tool schemas, measured here by running the
  bundle's own `register()` against a recording context, so what is counted is
  what the host is handed, not a list kept beside it. This is the eager
  ceiling, not the default per-request cost: Hermes's `tools.tool_search`
  defaults to `auto` (an alias of `on`), and `tools/tool_search.py::
  is_deferrable_tool_name` treats every non-core plugin tool as deferrable, so
  under the default the `omh_*` schemas sit behind the tool_search bridge and
  only a bounded name-and-description listing rides each request, plus the
  schemas of tools the model describes or calls. All of it is paid per request
  only when `tools.tool_search.enabled` is `off`, or on a host without the
  bridge;
- the fenced context `pre_llm_call` returns, which Hermes appends to the API
  copy of the user message and replays on every later turn from the
  `api_content` sidecar. Its parts come from several producers (route hint,
  role context, active workflow, running-work board, ...) joined with no
  aggregate cap, so it is measured over a fixed, named scenario set. The
  awareness primer is not one of them on a host with system prompt sections:
  there it is frozen into the session's system prompt instead
  (`awareness_system_prompt_section`), and only the fallback scenario
  measures it here.

The plugin bundle is imported from here, never the other way round: modules
under `src/plugin_bundle/omh/` must stay importable without `omh`
(`tests/test_plugin_bundle_standalone.py`).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

# The session every scenario runs under. Each scenario gets fresh OMH and
# Hermes homes, so nothing one scenario writes is visible to the next.
_SCENARIO_SESSION = "omh-per-turn-context-scenario"

# The running-work board shows at most this many rows (`read_running_work_board`
# is called with `limit=6` in `pre_llm_call`), so the scenario seeds exactly a
# full board.
_RUNNING_BOARD_UNITS = 6

# A request the router answers with a route hint; the hint is message-specific,
# so the scenario pins one message rather than claiming a bound over all of them.
_ROUTED_REQUEST = "review this PR for bugs before merge"
_PLAIN_REQUEST = "migrate the database schema and fix the tests"
# A work request the rule table has no cue for, so the turn's only routing
# text is the skill candidate line (`skill_shortlist`); three candidates, the
# most the line names.
_CANDIDATE_REQUEST = (
    "Activation fell after we changed the signup flow and new users churn in their first week. "
    "Where does retention break?"
)


# The row Hermes writes when a background process it was told to watch exits.
_PROCESS_COMPLETE_NOTICE = "[Background process proc_scenario finished with exit code 0]"
# The turn after Hermes' `/plan` wrote a plan, accepting it in words the router
# also routes, so the route hint, the active plan line and the plan follow-on
# line ride one turn (`plan_follow_on`).
_PLAN_ACCEPTANCE = "looks good, implement the plan"
_PLAN_TURN_HISTORY = (
    {"role": "user", "content": "[/plan \u2014 plan mode]\n\nFor this turn, you are in PLAN MODE \u2014 planning only.\n"},
    {"role": "assistant", "content": "Saved the plan to .hermes/plans/2026-11-04_101500-export.md. Carry it out?"},
)


class _RecordingPluginContext:
    """The two registration methods `register()` requires, recording what it passes."""

    def __init__(self) -> None:
        self.tool_schemas: dict[str, object] = {}
        self.hooks: dict[str, object] = {}

    def register_tool(self, name: str, toolset: str, schema: object, handler: object, **kwargs: object) -> None:
        self.tool_schemas[name] = schema

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks[name] = handler


def registered_tool_schemas() -> dict[str, object]:
    """Every tool schema the plugin bundle registers, keyed by tool name."""
    from ..plugin_bundle.omh import register

    context = _RecordingPluginContext()
    register(context)
    return dict(context.tool_schemas)


def _schema_chars(schema: object) -> int:
    return len(json.dumps(schema, sort_keys=True, ensure_ascii=False))


def plugin_tool_schema_chars_by_tool() -> dict[str, int]:
    return {name: _schema_chars(schema) for name, schema in sorted(registered_tool_schemas().items())}


def plugin_tool_schema_chars() -> int:
    """Total serialized size of the registered tool schemas (JSON, sorted keys, unescaped)."""
    return sum(plugin_tool_schema_chars_by_tool().values())


def _seed_active_workflow(omh_home: Path) -> None:
    state = omh_home / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "plan-state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workflow": "plan",
                "active": True,
                "lifecycle_outcome": None,
                "session_ref": "sha256:" + hashlib.sha256(_SCENARIO_SESSION.encode("utf-8")).hexdigest(),
                "session_binding": "bound",
            }
        ),
        encoding="utf-8",
    )


def _seed_running_board(omh_home: Path) -> None:
    from datetime import datetime, timezone

    from ..plugin_bundle.omh.run_records import INFLIGHT_MARKER_SCHEMA_VERSION

    inflight = omh_home / "coding" / "fanout" / "fanout-000000000000" / "inflight"
    inflight.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for index in range(_RUNNING_BOARD_UNITS):
        (inflight / f"u{index}.json").write_text(
            json.dumps(
                {
                    "schema_version": INFLIGHT_MARKER_SCHEMA_VERSION,
                    "owner": "codex",
                    "model": "gpt-6-astra",
                    "started_at": started_at,
                    "unit_state": "running",
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )


def _seed_done_unverified_plan(omh_home: Path) -> None:
    """A plan whose done item's bound command failed, and the store that says so.

    The session's own `state.db` sits in the Hermes home beside `omh_home`
    (`_run_pre_llm_call` makes both under one directory). The item carries
    the longest reason phrase the plan line renders, so the scenario measures
    the evidence clause and `TODO_EVIDENCE_RULE` at their largest.
    """
    import sqlite3
    import time
    from datetime import datetime, timezone

    from ..plugin_bundle.omh.todo_store import build_todo_record, write_todo

    now = time.time()
    hermes_home = omh_home.parent / "hermes"
    connection = sqlite3.connect(hermes_home / "state.db")
    try:
        connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
        connection.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
            "content TEXT, tool_call_id TEXT, tool_name TEXT, effect_disposition TEXT, timestamp REAL)"
        )
        connection.execute("INSERT INTO sessions VALUES (?, NULL)", (_SCENARIO_SESSION,))
        for call_id in ("scenario_bound", "scenario_unbound"):
            connection.execute(
                "INSERT INTO messages (session_id, role, content, tool_call_id, tool_name, timestamp) "
                "VALUES (?, 'tool', ?, ?, 'terminal', ?)",
                (_SCENARIO_SESSION, json.dumps({"exit_code": 0}), call_id, now - 30),
            )
        connection.commit()
    finally:
        connection.close()
    window = {
        "window_start": datetime.fromtimestamp(now - 60, timezone.utc).isoformat().replace("+00:00", "Z"),
        "done_at": datetime.fromtimestamp(now - 10, timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    items = [
        {"text": "land the fix", "state": "done", "evidence": {"kind": "tool_call", "ref": "scenario_bound"}, **window},
        {"text": "run the full suite and report the observed result", "state": "done", **window},
        {"text": "open the pull request", "state": "active"},
    ]
    write_todo(omh_home, build_todo_record("plan", items, source="omh_todo", session_ref=_SCENARIO_SESSION))


def _seed_held_native_write(omh_home: Path) -> None:
    """An open accepted plan, and a todo_list write its hold kept out.

    The write goes through the projection itself, so the line measured is
    the one a held write leaves for the next turn, beside the plan line the
    open plan carries.
    """
    from ..plugin_bundle.omh.native_todo import project_native_todo
    from ..plugin_bundle.omh.todo_store import PLAN_STAGE_ACCEPTED, build_todo_record, write_todo

    items = [
        {"text": "options and tradeoffs", "state": "done"},
        {"text": "lane a check: `make test`", "state": "active"},
    ]
    write_todo(
        omh_home,
        build_todo_record(
            "plan", items, source="omh_todo", session_ref=_SCENARIO_SESSION, plan_stage=PLAN_STAGE_ACCEPTED
        ),
    )
    todos = [{"id": "1", "content": "unrelated work", "status": "in_progress"}]
    project_native_todo(
        tool_name="todo_list",
        args={"todos": todos},
        result=json.dumps({"todos": todos}),
        status="ok",
        session_ref=_SCENARIO_SESSION,
        omh_home=str(omh_home),
        hermes_home=str(omh_home.parent / "hermes"),
    )


def _run_pre_llm_call(
    seeds: tuple[Callable[[Path], None], ...], *, section: bool = True, **kwargs: Any
) -> int:
    from ..plugin_bundle.omh.hooks import llm_hooks

    # `section` is whether the host rendered the awareness system prompt
    # section for this session, as every admitted host does; without it the
    # primer rides the fenced context, as on a host that lacks the API.
    from ..plugin_bundle.omh.skill_shortlist import reset_candidate_line_state

    llm_hooks._reset_awareness_section_state()
    # Every scenario runs under one session id; each measures a fresh session.
    reset_candidate_line_state()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / "omh"
            hermes_home = Path(tmp) / "hermes"
            omh_home.mkdir()
            hermes_home.mkdir()
            if section:
                # The render, then the session's own first turn confirming it,
                # so a later-turn scenario measures a session already past it.
                llm_hooks.awareness_system_prompt_section({"session_id": _SCENARIO_SESSION})
                llm_hooks._awareness_section_carries_primer(_SCENARIO_SESSION, is_first_turn=True)
            for seed in seeds:
                seed(omh_home)
            payload = llm_hooks.pre_llm_call(
                omh_home=str(omh_home),
                hermes_home=str(hermes_home),
                session_id=_SCENARIO_SESSION,
                **kwargs,
            )
    finally:
        llm_hooks._reset_awareness_section_state()
    return len(str((payload or {}).get("context", "")))


def _largest_role(message_suffix: str, seeds: tuple[Callable[[Path], None], ...], **kwargs: Any) -> int:
    from ..plugin_bundle.omh.omh_roles import role_names

    return max(
        _run_pre_llm_call(seeds, user_message=f"[omh-role:{role}] {message_suffix}", **kwargs)
        for role in role_names()
    )


def pre_llm_call_context_scenario_chars() -> dict[str, int]:
    """Fenced `pre_llm_call` context size per named scenario.

    Every scenario but the two `*_without_section` ones runs as on a host that
    rendered the awareness system prompt section for the session (Hermes
    0.20.2 and later, so every host the plugin admits), where the primer is in
    the system prompt and not here. The `*_without_section` pair measures the
    fallback, which still runs for a session the section did not render for
    (a restart resume, a legacy id-rotating compaction, a refused section):

    - `first_turn_without_section`: a session's first turn on a request with
      no OMH vocabulary, on a host that did not render the section (the primer
      alone, inside the fence). This is the fallback, not the default.
    - `route_hint`: a first turn on a routed request (the route hint).
    - `skill_candidates`: a later turn on a work request that gets the skill
      candidate line and no route hint.
    - `role_marker`: a later turn carrying an `[omh-role:...]` marker, the
      largest shipped role.
    - `active_workflow`: a later turn while a workflow is active.
    - `running_work_board`: a later turn with a full running-work board.
    - `done_unverified_plan`: a later turn, opened by a finished background
      process, with an open plan whose done item has commands in its window
      and none bound to it, so the plan line carries the evidence clause and
      `TODO_EVIDENCE_RULE`. The todo
      reminder is otherwise not seeded (see below); this measures the one
      part of it that grows a line.
    - `held_native_write`: a later turn after a todo_list write that an open
      accepted plan's hold kept out of the record, so the plan line and the
      one-time held-write line ride together.
    - `plan_acceptance`: a later turn accepting the plan Hermes' `/plan` wrote
      the turn before, while a plan workflow is active, so the route hint,
      the active plan line and the plan follow-on line ride together.
    - `all_surfaces_without_section`: `all_surfaces` on the fallback, primer
      included; the fallback's maximum.
    - `all_surfaces`: the route hint, candidate line, largest role, active
      workflow and running board in one first turn (the three plan scenarios
      above need a later turn and are not part of it). The parts add, so
      this is the largest of the seeded scenarios; it is not a bound on every
      turn, because the parts listed below are not seeded. The routed request
      also gets a candidate line, since the line stands down only for a
      workflow the person named.

    `pre_llm_call` can append these parts, none of which any scenario reaches,
    so the metric does not move when they grow:

    - the Kanban board card: capped at `_BOARD_CARD_MAX_CHARS`, and its
      fixture is Hermes's own `state.db`/`kanban.db`;
    - the open-plan (todo) reminder: bounded per plan by
      `TODO_RECONCILIATION_FULL_TURNS`, gated in
      `tests/test_injected_context_pressure.py`;
    - the context-budget continuation (`render_context_budget`): needs a
      recorded budget crossing for the session and model;
    - the `[OMH continuation claim]` line: one finding sentence, and needs a
      prior assistant turn in `conversation_history`;
    - the active-executor status block: bounded in line count (a HUD line,
      two fixed lines, the latest run id, at most 3 executors and 3 runs, one
      fixed pointer line) but not in characters, since those lines carry
      recorded ids, profiles and statuses; needs live executor records under
      `omh_home`;
    - the `[OMH Degraded]` line: a fixed sentence plus the failing component
      names, emitted only when a local call failed;
    - the `[OMH dag]` open-run line (`dag_open_run_nudge`): one fixed line
      per reason naming a run id and at most three node ids, once per
      situation, and needs a stored dag run with no node running.
    """
    no_seed: tuple[Callable[[Path], None], ...] = ()
    later = {"is_first_turn": False}
    return {
        "first_turn_without_section": _run_pre_llm_call(
            no_seed, section=False, user_message=_PLAIN_REQUEST, is_first_turn=True
        ),
        "route_hint": _run_pre_llm_call(no_seed, user_message=_ROUTED_REQUEST, is_first_turn=True),
        "skill_candidates": _run_pre_llm_call(no_seed, user_message=_CANDIDATE_REQUEST, **later),
        "role_marker": _largest_role("continue", no_seed, **later),
        "active_workflow": _run_pre_llm_call((_seed_active_workflow,), user_message="continue", **later),
        "running_work_board": _run_pre_llm_call((_seed_running_board,), user_message="continue", **later),
        # A turn the host opened for a finished background process: the plan
        # line then carries the drive and `TODO_EVIDENCE_RULE` rather than
        # the answer-first variant a person's message gets, which is the
        # larger of the two lines the evidence clause can ride.
        "done_unverified_plan": _run_pre_llm_call(
            (_seed_done_unverified_plan,),
            user_message=_PROCESS_COMPLETE_NOTICE,
            conversation_history=[
                {"role": "user", "content": _PROCESS_COMPLETE_NOTICE, "display_kind": "process_complete"}
            ],
            **later,
        ),
        "held_native_write": _run_pre_llm_call(
            (_seed_held_native_write,), user_message="continue", **later
        ),
        "plan_acceptance": _run_pre_llm_call(
            (_seed_active_workflow,),
            user_message=_PLAN_ACCEPTANCE,
            conversation_history=[*_PLAN_TURN_HISTORY, {"role": "user", "content": _PLAN_ACCEPTANCE}],
            **later,
        ),
        "all_surfaces": _largest_role(
            _ROUTED_REQUEST,
            (_seed_active_workflow, _seed_running_board),
            is_first_turn=True,
        ),
        "all_surfaces_without_section": _largest_role(
            _ROUTED_REQUEST,
            (_seed_active_workflow, _seed_running_board),
            section=False,
            is_first_turn=True,
        ),
    }


_WITHOUT_SECTION = "_without_section"


def pre_llm_call_context_chars_max() -> int:
    """The largest scenario on a host that rendered the awareness section."""
    scenarios = pre_llm_call_context_scenario_chars()
    return max(chars for name, chars in scenarios.items() if not name.endswith(_WITHOUT_SECTION))


def pre_llm_call_context_fallback_chars_max() -> int:
    """The largest scenario for a session the awareness section did not render for."""
    scenarios = pre_llm_call_context_scenario_chars()
    return max(chars for name, chars in scenarios.items() if name.endswith(_WITHOUT_SECTION))


# Each per-turn slot (`turn_budget.SLOT_LIMITS`) and the `budget_metrics()`
# entry whose producer measures it.
_SLOT_METRICS = {
    "primer": "awareness_primer_context_chars",
    "primer_markdown": "awareness_primer_markdown_chars",
    "workflow_context": "awareness_workflow_context_chars_max",
    "role_context": "role_context_chars_max",
    "pre_llm_call": "pre_llm_call_context_chars_max",
    "pre_llm_call_fallback": "pre_llm_call_context_fallback_chars_max",
}


def _slot_report(slot: str, metric: Any) -> dict[str, object]:
    from ..plugin_bundle.omh.turn_budget import SLOT_LIMITS

    limit = SLOT_LIMITS[slot]
    live = metric.live()
    return {"limit": limit, "live": live, "headroom": limit - live, "kind": metric.kind}


def budget_report() -> dict[str, dict[str, object]]:
    """Every per-turn slot's limit, live size, headroom, and budget kind, by slot."""
    from .drift import budget_metrics

    metrics = {metric.name: metric for metric in budget_metrics()}
    return {slot: _slot_report(slot, metrics[name]) for slot, name in _SLOT_METRICS.items()}


def headroom(slot: str) -> int:
    """Characters left under one slot's limit, measured by that slot's producer alone."""
    from .drift import budget_metrics

    if slot not in _SLOT_METRICS:
        raise KeyError(f"no per-turn slot {slot!r}; slots: {', '.join(sorted(_SLOT_METRICS))}")
    metric = next(metric for metric in budget_metrics() if metric.name == _SLOT_METRICS[slot])
    return int(_slot_report(slot, metric)["headroom"])


__all__ = [
    "budget_report",
    "headroom",
    "plugin_tool_schema_chars",
    "plugin_tool_schema_chars_by_tool",
    "pre_llm_call_context_chars_max",
    "pre_llm_call_context_fallback_chars_max",
    "pre_llm_call_context_scenario_chars",
    "registered_tool_schemas",
]
