"""`omh_dag`: a dag-ulw run's graph, kept by OMH and run by the parent agent with Hermes' own `delegate_task`.

The tool validates and records the plan (`dag_run.py`, one DAG core in
`dag_core.py`), says which nodes are ready and how many `delegate_task`
calls the host can take right now, and records the outcome the parent
settles for each node. It runs nothing: every child is Hermes', built by the
parent's own call.

Free slots come from Hermes' own state, read-only: the cap is
``delegation.max_concurrent_children`` (config, then the environment, then
Hermes' default of 10), and the calls in flight are this process's running
units in ``state.db`` ``async_delegations``. A call over the pool would run
blocking, so `ready` never hands out more calls than there are free slots.

Export to external coding owners (`export`) requires the owner to be named
in the request that defined the run: `define` copies the owners that turn's
request named (`named_owner_choice`) into the run, and only a coding node that
names one of them goes out. An earlier request's choice, an `omh chat` or
`omh coding` choice, or a recorded preference counts for nothing, and a node
without a chosen owner stays on `delegate_task`.

On a Docker or SSH terminal a child's `write_file` lands inside that
backend, not on this host. `define` records the backend Hermes resolves
(`terminal_backend`). Before the run's first node goes out, its handoff
root is pinned inside that terminal, under the terminal user's own home
(`backend_root`); with no terminal environment up yet, nothing goes out
and the result says to run one terminal command first. A home that does
not qualify keeps this host's path. `settle` reads the handoff through
Hermes' own live environment for the child (`backend_handoff`), under the
host check's rule; when that cannot be read, the node is accepted with
``handoff_checked: false``, and an interrupted read settles nothing. A
local backend, or one this does not read, keeps the host check alone.

With Hermes' `delegation.worktree_isolation` on and a local terminal, each
child would work in a worktree of its own made from the parent's HEAD,
without the earlier nodes' edits. `define` is then refused
(`worktree_isolation_on`), and for a run defined before, `ready` hands out no
`delegate_task` call and `status` says why (`worktree_isolation_on`).
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import sqlite3
import time
from typing import Any

from .. import dag_run, runtime_paths
from ..delegation_ledger import oneshot_children_spawned, read_ledger, with_unjoined_stop
from ..delegation_snapshot import dag_added_clause, shown_lanes
from ..delegation_backend_mode import (
    DEFAULT_BACKEND,
    Quoted,
    _Unsupported,
    category_options,
    delegation_section,
    read_backend_mode,
)
from ..delegation_routing import _config_path, _read_config_snapshot, read_delegation_settings
from ..hermes_delegation import effective_mixture_category_chains, load_model_provider_routes
from ..host_observation import host_session_id
from ..host_process import process_alive
from ..named_owner_choice import turn_owners
from ..sqlite_readonly import connect_readonly
from .lsp_nav_tool import _workspace_root

DEFAULT_MAX_CONCURRENT_CHILDREN = 10  # Hermes' `_DEFAULT_MAX_CONCURRENT_CHILDREN` (tools/delegate_tool_config.py)
# Hermes' default for `delegation.oneshot_max_children`: a finite one-shot session gets this many children at most.
DEFAULT_ONESHOT_MAX_CHILDREN = 2
MAX_CONCURRENT_ENV = "DELEGATION_MAX_CONCURRENT_CHILDREN"
UNREAD_SLOTS = 1  # when Hermes' state cannot be read: one call at a time, never a guessed wider wave
ACTIVE_UNIT_STATES = ("running", "stalling")
_UNIT_SUFFIX = re.compile(r"-\d+$")
# The owners are the executor table's, held equal by `tests/test_dag_tool.py`. An external coding CLI spends the
# person's money and quota, so a choice counts only for the request it was made in: the run keeps the owners its
# defining request named, and a later run asks again.
EXTERNAL_OWNERS = dag_run.EXTERNAL_OWNERS
SPAWN_PLAN_THRESHOLD = 4  # `fanout_contracts.FANOUT_SPAWN_PLAN_THRESHOLD`, held by the same test
SPAWN_PLAN_FIELDS = ("why_parallel", "why_not_single_unit", "independence", "expected_evidence_shape")
# A call that names no run, before this conversation has one: the next call to make, never only a refusal.
NO_RUN_YET_SAY = (
    "No dag run in this conversation yet. A dag-ulw request starts with omh_dag action=define; the calls it "
    "returns carry the node markers the run view draws. Do not dispatch delegate_task for it before define."
)
# Hermes terminal backends where a child's files land out of this host's sight: a container, or another machine.
REMOTE_BACKENDS = ("docker", "ssh")
BACKEND_READ_SECONDS = 10  # the one `test` a settle runs there; a backend that has not answered by then is unread
# One line per verdict, as Hermes' own probe echoes them (`ShellFileOperations._probe_regular_file`): a shell that did
# not run prints none of them, so it is never taken for a missing file.
_HANDOFF_FILE, _HANDOFF_LINK, _HANDOFF_NONE = "OMH_HANDOFF_FILE", "OMH_HANDOFF_LINK", "OMH_HANDOFF_NONE"
# What a run on a Docker or SSH terminal says, each time, while no environment is up to find its handoff root in.
# Same turn: on a session-isolated Docker terminal a later turn may get another task id, and so another environment.
TERMINAL_FIRST = ("No node was handed out: the children write their handoff files in the {backend} terminal, and "
                  "none is up yet to find where. In this same turn, run one terminal command there (for example "
                  "`pwd`; a file tool brings it up too), then call omh_dag action=ready.")
TERMINAL_INTERRUPTED = ("No node was handed out: reading where the children write their handoff files in the {backend} "
                        "terminal was interrupted. Call omh_dag action=ready again.")
# Hermes' `delegation.worktree_isolation` gives each delegated child its own git worktree and branch from the parent's
# HEAD (`tools/subagent_worktree.py`). A dag run's dependents and its verify node read the earlier nodes' edits from
# one shared tree, so with it on a verify node could pass a tree without the work: `define` is refused and `ready`
# hands out nothing. OMH never writes the setting.
WORKTREE_ISOLATION_WHY = (
    "dag-ulw needs its delegated nodes to share one worktree, and this profile turns on Hermes' "
    "delegation.worktree_isolation: each node would start from the last commit without the earlier nodes' edits, so "
    "the verify node could pass a tree without the work. Ask the person to turn it off for this profile with "
    "`hermes config set delegation.worktree_isolation false` (or in the profile's config.yaml); OMH never changes it.")
WORKTREE_ISOLATION_REFUSED = WORKTREE_ISOLATION_WHY + " Then define the run again, or do the work without dag-ulw."
WORKTREE_ISOLATION_HELD = "No node was handed out: " + WORKTREE_ISOLATION_WHY + " Then call omh_dag action=ready."
# The plain scalars PyYAML (YAML 1.1) reads as false or as a zero number. Hermes reads the key with `bool()`, so every
# other value is on: a quoted one ('false' too), `y`, `enabled`, `1.0`, a non-empty list or mapping.
_YAML_FALSE = ("false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF")
_YAML_ZERO = re.compile(r"[-+]?(?:0[0_]*|0x[0_]+|0b[0_]+|0[0_]*\.[0_]*(?:[eE][-+][0-9]+)?|\.[0_]+(?:[eE][-+][0-9]+)?)")
_HOME_LINE, _HOME_UNUSABLE = "OMH_BACKEND_HOME=", "OMH_BACKEND_HOME_UNUSABLE"
# A home a handoff root may sit in: absolute, plain characters, and not one of the temp directories every user can
# write, where another user could plant a handoff file.
_HOME_PATH = re.compile(r"(?:/[A-Za-z0-9._@+-]+)+")
_SHARED_DIRS = ("/tmp", "/var/tmp", "/dev/shm", "/private/tmp", "/private/var/tmp")
# What a shell can glue to a line of its output, stripped before a verdict is read, as Hermes strips it
# (`file_operations_common._strip_terminal_fence_leaks`): OSC sequences, Hermes' fence markers, CSI sequences, BEL.
_TERMINAL_ESCAPES = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|'?\x07?__HERMES_FENCE_[A-Za-z0-9]+__\x07?'?|\x1b\[[0-?]*[ -/]*[@-~]|\x07")

_ACTIONS = ("define", "ready", "settle", "repair", "extend", "status", "cancel", "export")

OMH_DAG_SCHEMA = {
    "name": "omh_dag",
    "description": (
        "Keep a dag-ulw run: small nodes the parent dispatches via delegate_task. define records nodes "
        "(id, label, category, prompt with TASK / DELIVERABLE / SCOPE / VERIFY / STOP WHEN, depends_on, "
        "write_scope, role, owner) and refuses cycles, unknown or self-edges, write scopes shared without an edge, more "
        "than 48 nodes, and prompts naming none of the markers; a one-shot session caps nodes at "
        "delegation.oneshot_max_children. Lint is advice. ready returns delegate_task calls per category "
        "within the free slots: route each via omh_delegate_route, then delegate_task unchanged. After each "
        "child, read the node's handoff and settle it accepted, failed or blocked; a child saying it is "
        "blocked is blocked, never accepted. A still-running wait may settle parked with "
        "handle and wake_at (future UTC ISO-8601 or epoch, within 24h); ready reoffers it then, at most three parks. "
        "settle returns what is next. repair adds nodes for a failed "
        "node, at most two cycles. extend adds nodes to an all-passed run when the goal check finds work "
        "missing, at most two rounds. Past either limit, report what is open. Relay any `say` once."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "run": {"type": "string", "description": "Short lowercase run id (a-z, 0-9, -)."},
            "name": {"type": "string"},
            "goal": {"type": "string", "description": "define: the run's goal criteria, one line."},
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "category": {"type": "string", "enum": list(dag_run.CATEGORIES)},
                        "prompt": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "write_scope": {"type": "array", "items": {"type": "string"}},
                        "role": {"type": "string", "enum": list(dag_run.ROLES)},
                        "owner": {"type": "string", "enum": list(EXTERNAL_OWNERS)},
                    },
                    "required": ["id", "label", "category", "prompt"],
                },
            },
            "node": {"type": "string",
                     "description": "settle / repair: the node id. extend: the node whose check found the gap."},
            "outcome": {"type": "string", "enum": list(dag_run.OUTCOMES)},
            "reason": {"type": "string"},
            "handle": {"type": "string", "maxLength": dag_run.MAX_HANDLE_CHARS,
                       "description": "settle parked: the still-running background process or CI run handle."},
            "wake_at": {"type": ["string", "number"],
                        "description": "settle parked: UTC ISO-8601 or epoch; future, at most 24 hours ahead."},
            "provider_error": {
                "type": "boolean",
                "description": "settle failed: the child died on a provider error (an HTTP 400, no model call).",
            },
            "owner": {"type": "string", "enum": list(EXTERNAL_OWNERS),
                      "description": "export: the coding owner the person already chose."},
            "spawn_plan": {"type": "object"},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}


def omh_dag_handler(args: Mapping[str, object], **kwargs: object) -> str:
    action = str(args.get("action", ""))
    if action not in _ACTIONS:
        return _refused(action, "invalid_action", f"Use one of: {', '.join(_ACTIONS)}.")
    if _BUNDLE_IMPORT_FAILURE:
        return _refused(action, "omh_dag_unavailable", "This install cannot keep a dag run.",
                        detail=f"bundle_module_unimportable:{_BUNDLE_IMPORT_FAILURE}")
    try:
        session_is_delegated = _nudge_budget.session_is_delegated
        reading_session_id = _runtime_reader.reading_session_id
        conversation_session_ids = _kanban_board_reader.conversation_session_ids
    except AttributeError:
        return _refused(action, "omh_dag_unavailable", "This install cannot keep a dag run.",
                        detail="bundle_module_incomplete")
    try:
        session = host_session_id(dict(kwargs))
        hermes_home = runtime_paths.default_hermes_home()
        omh_home = runtime_paths.default_omh_home()
        if session and session_is_delegated(session, omh_home=str(runtime_paths.plugin_home(None))):
            return _refused(action, "called_from_child", "A node's own child cannot define or settle the run.")
        durable = reading_session_id(hermes_home, session)
        if not durable:
            return _refused(action, "session_required", "A dag run needs a named chat session.")
        segments = sorted({durable, *conversation_session_ids(hermes_home, durable)})
        now = time.time()
        limits, ignored = dag_limits(hermes_home)
        # The lanes this conversation's chat posts showed, so a status line names a node added since then once.
        shown = shown_lanes(omh_home, segments)
        # The parent's own task id, whose terminal environment its children share (`backend_root`).
        task = str(kwargs.get("task_id") or "default")
        if action == "define":
            return _define(args, omh_home, hermes_home, durable, segments, now, shown, task, limits=limits,
                           ignored=ignored, chosen=turn_owners(session))
        found = _find(omh_home, segments, args.get("run"))
        if found is None and not args.get("run"):
            return _refused(action, "run_not_found", NO_RUN_YET_SAY)
        if found is None:
            return _refused(action, "run_not_found", "No dag run by that id in this conversation; define it first.")
        record, path = found
        # Read before anything changes: a detector that cannot answer refuses the call with the record untouched.
        budget = oneshot_budget(hermes_home, segments) if action in ("ready", "settle", "repair", "extend") else None
        with dag_run.locked(path):
            record = dag_run.read_run(path) or record
            children = _children(omh_home, segments, hermes_home)
            derived = dag_run.derive(record, children, now)
            if action == "status":
                # As `ready` would split them: a coding node the chosen owner takes is no delegate_task call.
                offered = dag_run.offerable(record, derived, now, limits=limits)
                exports, owner_say = _owner_exports(record, derived, offered)
                coding = [node_id for entry in exports for node_id in entry["nodes"]]
                say = WORKTREE_ISOLATION_HELD if _isolation_holds(record, offered, coding, hermes_home) else ""
                say = " ".join(part for part in (say, _export_say(exports), owner_say) if part)
                return _result(action, record, derived, shown, say=say, extra=_export_fields(exports),
                               now=now, limits=limits, ignored=ignored)
            if action == "cancel":
                # Derive reports a cancelled run's running nodes as `cancelled`, so the live children are
                # read with the mark lifted: a repeated cancel names the same children the first one did.
                unmarked = {**record, "cancelled_at": None}
                live = dag_run.running_children(unmarked, dag_run.derive(unmarked, children, now), now)
                if record.get("cancelled_at") is None:
                    record["cancelled_at"] = now
                    record["updated_at"] = now
                    dag_run.write_run(path, record)
                derived = dag_run.derive(record, children, now)
                if live:
                    named = ", ".join(
                        f"{row['id']} as subagent {row['subagent_id']} ({dag_run.age_text(row['open_for_s'])} open)"
                        for row in live)
                    say = (
                        f"The run is cancelled. {len(live)} {'child is' if len(live) == 1 else 'children are'} "
                        f"still running ({named}) and finish on their own unless stopped; stop each with "
                        "delegate_task action=stop if it should not finish. The cancelled run never settles them.")
                else:
                    say = ("The run is cancelled. No child is still running.")
                return _result(action, record, derived, shown, say=say,
                               extra={"still_running": live} if live else None,
                               now=now, limits=limits, ignored=ignored)
            if action == "ready":
                return _ready(action, record, path, derived, children, omh_home, hermes_home, now, shown, task=task,
                              budget=budget, limits=limits, ignored=ignored)
            if action == "settle":
                node = dag_run.valid_id(args.get("node"), "invalid_node_id", "Name the node to settle.")
                backend = record.get("backend")

                def read() -> tuple[bool, str]:
                    # Called by `settle` only once its other checks passed. The child wrote the file under its own
                    # task id, its subagent id; with no child bound, the parent's, whose environment its children share.
                    child = derived[node].get("child") or {}
                    return read_handoff(record, omh_home, node, str(child.get("subagent_id") or task))

                happened = dag_run.settle(
                    record, derived, node, args.get("outcome"), args.get("reason"), _flag(args.get("provider_error")),
                    read_handoff=read, now=now, handle=args.get("handle"), wake_at=args.get("wake_at"),
                )
                record["updated_at"] = now
                dag_run.write_run(path, record)
                derived = dag_run.derive(record, children, now)
                say = ("The child hit a provider error: its node is offered once more on the route's fallback."
                       if happened == "retry" else "")
                unread = str(next(item for item in record["nodes"] if item["id"] == node)["attempts"][-1]
                             .get("handoff_unread") or "")
                if happened == "accepted" and unread:
                    say = (f"Node {node} is accepted, but its handoff was not checked: OMH could not read the {backend} "
                           f"terminal the child wrote it in ({unread}). The nodes after it read that file; if it is "
                           "not there, they stop and say so.")
                return _ready(action, record, path, derived, children, omh_home, hermes_home, now, shown, task=task,
                              say=say, settled={"node": node, "outcome": happened}, budget=budget, limits=limits, ignored=ignored)
            if action == "repair":
                node = dag_run.valid_id(args.get("node"), "invalid_node_id", "Name the failed node to repair.")
                added = dag_run.repair(record, derived, node, args.get("nodes"), now,
                                       oneshot_remaining=_wave_budget(record, derived, budget, now, limits=limits))
                dag_run.write_run(path, record)
                derived = dag_run.derive(record, children, now)
                group_node = next(item for item in record["nodes"] if item["id"] == added[0])
                replan = (f"This is {group_node['repairs']}'s last repair cycle; its nodes are briefed to re-plan "
                          "from the earlier failures."
                          if group_node["cycle"] == dag_run.REPLAN_CYCLE else "")
                return _ready(action, record, path, derived, children, omh_home, hermes_home, now, shown, task=task,
                              settled={"node": node, "repair_nodes": added}, budget=budget, limits=limits,
                              ignored=ignored, note=replan)
            if action == "extend":
                added = dag_run.extend(record, derived, args.get("nodes"), args.get("node"), now,
                                       oneshot_remaining=_wave_budget(record, derived, budget, now, limits=limits))
                dag_run.write_run(path, record)
                derived = dag_run.derive(record, children, now)
                return _ready(action, record, path, derived, children, omh_home, hermes_home, now, shown, task=task,
                              settled={"extend_round": len(record["extends"]), "extend_nodes": added,
                                       "found_by": record["nodes"][-1]["found_by"]}, budget=budget, limits=limits, ignored=ignored)
            return _export(args, record, path, derived, children, omh_home, now, shown, limits=limits, ignored=ignored)
    except dag_run.DagRefusal as refusal:
        return _refused(action, refusal.reason, refusal.say)
    except (runtime_paths.RuntimeBindingError, OSError, ValueError):
        # Never echo exception strings or paths.
        return _refused(action, "dag_store_unavailable", "The dag run record could not be reached.")
    except (KeyError, TypeError):
        return _refused(action, "dag_store_unreadable", "The dag run record could not be read.")


def _single_query_session() -> bool:
    """Hermes' finite one-shot marker (`hermes chat -q`), read where the host keeps it.

    Imported at call time: `agent` is the host's package and may not be on this
    install's path, where the session is simply not one-shot. Only an import
    missing exactly `agent` or `agent.oneshot_footprint` is optional absence.
    An installed detector's dependency or invocation failure is refused by name
    (`oneshot_detection_unavailable`) rather than answered `False`, because
    `False` means "interactive, no cap" and would silently drop the budget.
    """
    try:
        try:
            from agent.oneshot_footprint import is_single_query_session
        except ModuleNotFoundError as error:
            if error.name in {"agent", "agent.oneshot_footprint"}:
                return False
            raise
        # The callable (and truth conversion) can fail too; neither is absence.
        return bool(is_single_query_session())
    except Exception:
        # Classified and surfaced, never relabeled as a healthy answer: the
        # caller refuses by name and the exception text stays out of it.
        raise dag_run.DagRefusal(
            "oneshot_detection_unavailable",
            "OMH could not read whether this session is a one-shot `hermes chat -q`, so it will not "
            "define a dag run without knowing the child budget. Retry the define in a fresh session; "
            "if this repeats, repair the Hermes install that provides the one-shot detector.",
        ) from None


def oneshot_child_limit(hermes_home: Path) -> int | None:
    """`delegation.oneshot_max_children` in a one-shot session, else ``None`` (no cap here).

    ``0`` means unlimited. A value that is not a positive integer falls back to
    Hermes' own default, so a malformed or negative setting never silently
    becomes unlimited.
    """
    if not _single_query_session():
        return None
    raw = read_delegation_settings(hermes_home, ("oneshot_max_children",)).get("oneshot_max_children", "")
    try:
        limit = int(raw) if raw else DEFAULT_ONESHOT_MAX_CHILDREN
    except (TypeError, ValueError):
        limit = DEFAULT_ONESHOT_MAX_CHILDREN
    if limit == 0:
        return None
    return limit if limit > 0 else DEFAULT_ONESHOT_MAX_CHILDREN


def oneshot_budget(hermes_home: Path, segments: list[str]) -> dict[str, int] | None:
    """The one-shot child budget: ``limit``, the top-level children this process already started in the
    conversation (``spent``), and what is left; None outside a one-shot session or with no cap.

    Hermes keeps its own count per process (`_oneshot_children_spawned`) and refuses a whole `delegate_task` call
    over it; this count is the `subagent_start` hooks of the same process (`oneshot_children_spawned`).
    """
    limit = oneshot_child_limit(hermes_home)
    if limit is None:
        return None
    spent = oneshot_children_spawned(segments)
    return {"limit": limit, "spent": spent, "remaining": max(0, limit - spent)}


def _awaiting_dispatch(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], now: float, *,
                       limits: dag_run.Limits = dag_run.DEFAULT_LIMITS) -> list[str]:
    """Nodes handed to delegate_task that no child took yet and that are not offered again: each will cost a child."""
    offered = set(dag_run.offerable(record, derived, now, limits=limits))
    return [str(node["id"]) for node in record["nodes"]
            if derived[str(node["id"])]["state"] == "handed_out" and not derived[str(node["id"])].get("lost")
            and str(node["id"]) not in offered
            and (node.get("attempts") or [{}])[-1].get("lane") not in ("fanout", "parent")]


def _wave_budget(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]],
                 budget: Mapping[str, int] | None, now: float, *,
                 limits: dag_run.Limits = dag_run.DEFAULT_LIMITS) -> int | None:
    """How many more children this run may hand out now: the budget left, less the calls not yet dispatched."""
    if budget is None:
        return None
    return max(0, budget["remaining"] - len(_awaiting_dispatch(record, derived, now, limits=limits)))


def _define(args: Mapping[str, object], omh_home: Path, hermes_home: Path, durable: str, segments: list[str],
            now: float, shown: set[str] | None, task: str, *, limits: dag_run.Limits = dag_run.DEFAULT_LIMITS,
            ignored: tuple[str, ...] = (), chosen: tuple[str, ...] = ()) -> str:
    if worktree_isolation_on(hermes_home, terminal_backend()):
        raise dag_run.DagRefusal("worktree_isolation_on", WORKTREE_ISOLATION_REFUSED)
    run = dag_run.valid_id(args.get("run"), "invalid_run_id", "Give the run a short lowercase id (a-z, 0-9, -).")
    budget = oneshot_budget(hermes_home, segments)
    record = dag_run.new_record(durable, run, args.get("name"), args.get("goal"), args.get("nodes"), now,
                                oneshot_limit=budget["limit"] if budget else None,
                                oneshot_spent=budget["spent"] if budget else 0, named_roles=False)
    found = _find(omh_home, segments, run)
    if found is not None:
        existing, path = found
        if existing.get("digest") != record["digest"]:
            raise dag_run.DagRefusal(
                "run_exists",
                f"Run {run} already exists with other nodes; use repair or extend to add nodes, or a new run id.")
        children = _children(omh_home, segments, hermes_home)
        derived = dag_run.derive(existing, children, now)
        return _result("define", existing, derived, shown, say="This run was already defined; nothing changed.",
                       extra={"reused": True}, now=now, limits=limits, ignored=ignored)
    dag_run.require_named_roles(args["nodes"])  # a new definition names the role of a node that reads like a check
    if not dag_run.make_room(omh_home, durable, _children(omh_home, segments, hermes_home), now):
        raise dag_run.DagRefusal(
            "too_many_runs", "This conversation already keeps the most dag runs it can; cancel one that is not needed.")
    path = dag_run.record_path(omh_home, durable, run)
    with dag_run.locked(path):
        if dag_run.read_run(path) is not None:
            raise dag_run.DagRefusal("run_exists", f"Run {run} was just defined by another call.")
        (path.parent / run).mkdir(parents=True, exist_ok=True, mode=0o700)
        backend = terminal_backend()
        if backend:
            record["backend"] = backend  # where the children's handoff files land; `settle` reads them there
        owners = sorted(owner for owner in set(chosen) if owner in EXTERNAL_OWNERS)
        if owners:
            # The coding owners this turn's request named: the run keeps them, and nothing else chooses one.
            record["owners"] = owners
        workspace = _workspace_root(task)
        if workspace:
            # The root a node's write_scope is read against (`dag_scope_guard`), fixed here so a child's `cd` cannot
            # move it.
            record["workspace_root"] = os.path.realpath(workspace)
        dag_run.write_run(path, record)
        derived = dag_run.derive(record, [], now)
        return _ready("define", record, path, derived, [], omh_home, hermes_home, now, shown, task=task, budget=budget,
                      limits=limits, ignored=ignored)


def _find(omh_home: Path, segments: list[str], run: object) -> tuple[dict[str, Any], Path] | None:
    """The named run under any segment of this conversation, or with no name its newest run."""
    runs = [item for segment in segments for item in dag_run.session_runs(omh_home, segment)]
    if isinstance(run, str) and run:
        runs = [item for item in runs if item[0].get("run") == run]
    runs.sort(key=lambda item: float(item[0].get("updated_at") or 0.0), reverse=True)
    return runs[0] if runs else None


def _children(omh_home: Path, segments: list[str], hermes_home: Path | None = None) -> list[dict[str, Any]]:
    """Every child the delegation ledgers of this conversation's segments hold.

    A stop Hermes filed under another segment (a parent its rotating
    compaction moved since the child started) is joined to the child it
    names first (`with_unjoined_stop`), so a child that came back is not
    taken for one a restart ended. One with no stop whose Hermes process is
    gone is marked ``lost``: a restart ended it, and Hermes fires no
    `subagent_stop` for it. Only a process Hermes' own probes say ended
    counts (`host_process.process_alive`). Before that mark, with
    ``hermes_home``, a child's own lineage is read: a child Hermes rotated
    since it started stops under its continuation's id, and a stop naming a
    later segment of it is its own. That is the only state.db read here,
    and only for a child about to be marked lost while a stop is unjoined.
    """
    children: list[dict[str, Any]] = []
    stops: list[dict[str, Any]] = []
    for segment in segments:
        ledger = read_ledger(omh_home, segment)
        if ledger:
            children.extend(ledger["children"])
            stops.extend(ledger["unjoined_stops"])
    if stops:
        children = [with_unjoined_stop(child, stops) for child in children]
    alive: dict[tuple[int, int | None, str], bool | None] = {}
    for index, child in enumerate(children):
        host = child.get("host")
        if "stop" in child or host is None:
            continue
        key = (host["pid"], host["started"], host["machine"])
        if key not in alive:
            alive[key] = process_alive(host)
        if alive[key] is not False:
            continue
        if stops and hermes_home is not None:
            session = child["child_session_id"]
            later = sorted(_kanban_board_reader.conversation_session_ids(hermes_home, session) - {session})
            returned = with_unjoined_stop(child, stops, later) if later else child
            if "stop" in returned:
                children[index] = returned
                continue
        child["lost"] = True
    return children


def free_slots(hermes_home: Path, *, pid: int | None = None) -> dict[str, Any]:
    """How many more background `delegate_task` calls the host admits now, from its own config and state.db."""
    settings = read_delegation_settings(hermes_home, ("max_concurrent_children", "independent_completions"))
    cap = _cap(settings.get("max_concurrent_children"))
    owner = os.getpid() if pid is None else pid
    used: set[str] = set()
    state_db = Path(hermes_home) / "state.db"
    basis = "state_db"
    try:
        if not state_db.is_file():
            raise sqlite3.OperationalError("no state.db")
        connection = connect_readonly(state_db, timeout=0.25)
        try:
            rows = connection.execute(
                "SELECT delegation_id FROM async_delegations WHERE state IN (?, ?) AND owner_pid = ?",
                (*ACTIVE_UNIT_STATES, owner),
            ).fetchall()
        finally:
            connection.close()
        # The units of one call share its pool slot; Hermes names them `<call id>-<n>`.
        used = {_UNIT_SUFFIX.sub("", str(row[0])) for row in rows if row and row[0]}
    except sqlite3.Error:
        basis = "unread"
    free = max(0, cap - len(used)) if basis == "state_db" else min(UNREAD_SLOTS, cap)
    return {"cap": cap, "running_calls": len(used) if basis == "state_db" else None, "free": free, "basis": basis,
            "independent_completions": str(settings.get("independent_completions", "")).casefold() in ("true", "yes", "on")}


def worktree_isolation_on(hermes_home: Path, backend: str = "") -> bool:
    """Whether Hermes would give each delegated child a worktree of its own. Read-only.

    Hermes' own answer first, imported at call time: `_get_worktree_isolation`
    (its config loader, so the managed overlay, ``HERMES_IGNORE_USER_CONFIG``
    and env expansion count) and `local_backend_active` (a Docker or SSH
    terminal skips isolation). Outside Hermes, or when either moved or raised:
    off on a Docker or SSH ``backend``, else this profile's config.yaml read
    the way Hermes reads it (`_isolation_in_config`). Hermes also skips
    isolation outside a git checkout; that is not told apart.
    """
    try:
        from tools.delegate_tool import _get_worktree_isolation
        from tools.subagent_worktree import local_backend_active

        return bool(_get_worktree_isolation()) and bool(local_backend_active())
    except Exception:
        # Not Hermes (ImportError), or a Hermes whose getters moved or raised: the config file, read the same way.
        pass
    if backend in REMOTE_BACKENDS:
        return False
    return _isolation_in_config(hermes_home)


def _isolation_in_config(hermes_home: Path) -> bool:
    """`delegation.worktree_isolation` in this profile's config.yaml, as `bool()` over PyYAML's value.

    Off when the key is absent, null, empty, or a plain false or zero scalar
    (`_YAML_FALSE`, `_YAML_ZERO`); every other value is on. A config that
    cannot be read counts as off (today's behaviour). A `delegation` section
    this reader cannot place (a flow mapping, a block scalar, an anchor)
    counts as on when the file names the key anywhere, since Hermes may read
    it on.
    """
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return False
    try:
        section = delegation_section(text)
    except _Unsupported:
        return "worktree_isolation" in text
    value = (section or {}).get("worktree_isolation")
    if isinstance(value, Quoted) or not isinstance(value, str):
        return bool(value)
    return value not in _YAML_FALSE and _YAML_ZERO.fullmatch(value) is None


def _cap(configured: object) -> int:
    for value in (configured, os.environ.get(MAX_CONCURRENT_ENV, "")):
        try:
            if value not in (None, ""):
                return max(1, int(str(value)))
        except ValueError:
            continue
    return DEFAULT_MAX_CONCURRENT_CHILDREN


def terminal_backend() -> str:
    """``docker`` or ``ssh`` when Hermes runs this profile's terminal there, else "".

    The backend comes from Hermes' own resolver
    (`tools.terminal_tool._get_env_config`, which reads the profile's
    settings), imported at call time; when it cannot be imported or raises,
    from ``TERMINAL_ENV``, the variable it reads. ``local``, a backend not in
    `REMOTE_BACKENDS`, and nothing readable give "": the host check alone, as
    before.
    """
    try:
        from tools.terminal_tool import _get_env_config

        backend = _get_env_config()["env_type"]
    except Exception:
        # Not Hermes (ImportError), or a resolver that moved or raised on a bad TERMINAL_* value: the variable it reads.
        backend = os.environ.get("TERMINAL_ENV", "")
    name = str(backend or "").strip().casefold()
    return name if name in REMOTE_BACKENDS else ""


def read_handoff(record: Mapping[str, Any], omh_home: Path, node: str, task_id: str) -> tuple[bool, str]:
    """A node's handoff, (found, unread).

    Under a pinned backend root, read in that backend only (the path names no
    file of this host). Otherwise the host check, then, for a run kept on a
    Docker or SSH terminal, the same path in that backend.
    """
    if record.get("handoff_root"):
        return backend_handoff(dag_run.node_handoff(record, omh_home, node), task_id)
    path = dag_run.handoff_path(omh_home, str(record["session_id"]), str(record["run"]), node)
    if path.is_file() and not path.is_symlink():
        return True, ""
    if record.get("backend") not in REMOTE_BACKENDS:
        return False, ""
    return backend_handoff(str(path), task_id)


def backend_handoff(path: str, task_id: str) -> tuple[bool, str]:
    """Whether a handoff is a regular file and no link inside the terminal backend a child wrote it in: (found, unread).

    ``unread`` names why there is no answer (`_backend_lines`), and ``found``
    is then False. A read the parent's interrupt stopped refuses the settle
    and records nothing, so the parent settles again.
    """
    quoted = shlex.quote(path)
    lines, unread = _backend_lines(task_id, f"if [ -L {quoted} ]; then echo {_HANDOFF_LINK}; elif [ -f {quoted} ]; "
                                            f"then echo {_HANDOFF_FILE}; else echo {_HANDOFF_NONE}; fi")
    if unread == "interrupted":
        raise dag_run.DagRefusal("settle_interrupted", "The handoff check was interrupted, so nothing was settled; "
                                                       "settle the node again.")
    if unread:
        return False, unread
    verdicts = {line.strip() for line in lines}
    if _HANDOFF_FILE in verdicts:
        return True, ""
    if _HANDOFF_LINK in verdicts or _HANDOFF_NONE in verdicts:
        return False, ""
    return False, "backend_unanswered"


def backend_root(task_id: str) -> tuple[str | None, str]:
    """Where a run on a Docker or SSH terminal keeps its handoff files: (``<home>/.omh/dag`` in that terminal, why not).

    The home is the backend user's ``$HOME``, read once through the parent's
    live environment and resolved to its physical path (``cd -P``, ``pwd -P``),
    so a home that is a link is judged, and pinned, as the directory it points
    at. It is taken only as a directory that user can write and that no other
    user can (neither group- nor world-writable), at a plain absolute path
    outside the shared temp directories; the shell refuses a ``$HOME`` with
    whitespace in it or a relative one, and exactly one home line must come back.
    The check fails closed: ``cd``, ``pwd`` and ``find`` run as ``command``
    (Hermes' snapshot carries the login shell's functions and aliases), and
    the home qualifies only when `find` itself prints it back as neither
    group- nor world-writable; a `find` that prints nothing refuses it. A child's
    `write_file` takes the absolute path as it is in the backend; ``~`` would
    not do, since on Docker Hermes expands it on this host.

    "" keeps this host's path for the run, as before: a home that does not
    qualify, or a backend that cannot be read or does not answer. None pins
    nothing, with the reason: ``environment_gone`` (no environment is live
    yet, and none is started for this) or ``interrupted``.
    """
    lines, unread = _backend_lines(task_id, (
        'if case "$HOME" in *[[:space:]]*) false ;; /*) true ;; *) false ;; esac '
        '&& home="$(command cd -P -- "$HOME" 2>/dev/null && command pwd -P)" '
        '&& case "$home" in /*[[:space:]]*|"") false ;; /*) true ;; *) false ;; esac '
        '&& [ -d "$home" ] && [ -w "$home" ] '
        '&& [ "$(command find "$home" -prune ! -perm -0002 ! -perm -0020 -print 2>/dev/null)" = "$home" ]; '
        f"then command printf '%s%s\\n' {_HOME_LINE} \"$home\"; else echo {_HOME_UNUSABLE}; fi"))
    if unread in ("environment_gone", "interrupted"):
        return None, unread
    homes = [line[len(_HOME_LINE):] for line in lines if line.startswith(_HOME_LINE)]
    home = homes[0] if len(homes) == 1 else ""
    usable = (_HOME_PATH.fullmatch(home) is not None and posixpath.normpath(home) == home
              and not any(home == shared or home.startswith(shared + "/") for shared in _SHARED_DIRS))
    return (f"{home}/.omh/dag" if usable else ""), ""


def _backend_lines(task_id: str, command: str) -> tuple[list[str], str]:
    """The output lines of one command in Hermes' live environment for ``task_id``, terminal escapes stripped.

    A line keeps its own spaces: a caller that compares a verdict strips it,
    and one that reads a value takes it as it was printed.

    The environment is the one `get_active_env` returns, which follows a
    delegated child to its parent's environment, the one the child's
    `write_file` ran in; with none live, nothing runs. The command goes
    through `BaseEnvironment.execute`, not the backend's own `execute`, so
    Docker's recovery (`DockerEnvironment.execute` restarts or recreates a
    container that went away) is never entered from here and its notice stays
    for the parent's next terminal call. It passes no cwd, so the cwd marker
    the environment writes back leaves the shared shell where it was. On SSH
    it rides the connection Hermes keeps, which opens a new one when its
    shared master expired (``ControlMaster=auto``).

    The second item names why there are no lines: ``no_read_path`` (Hermes'
    environment registry is not importable here, or raised, or the
    environment is no `BaseEnvironment`), ``environment_gone`` (no live
    environment for the task: its idle reaper or a close ended it, or this
    is another process), ``interrupted`` (the parent's interrupt stopped the
    command), ``backend_unanswered`` (the backend raised).
    """
    try:
        from tools.environments.base import BaseEnvironment
        from tools.terminal_tool_lifecycle import get_active_env

        environment = get_active_env(task_id)
    except Exception:
        # Not Hermes, or a Hermes whose environment registry moved or raised: nothing reaches the backend.
        return [], "no_read_path"
    if environment is None:
        return [], "environment_gone"
    if not isinstance(environment, BaseEnvironment):
        return [], "no_read_path"
    try:
        answer = BaseEnvironment.execute(environment, command, timeout=BACKEND_READ_SECONDS)
    except Exception:
        # The backend raised (a dropped connection, a removed container): no lines, so no verdict either.
        return [], "backend_unanswered"
    if isinstance(answer, Mapping) and answer.get("hermes_interrupted"):
        return [], "interrupted"
    output = answer.get("output") if isinstance(answer, Mapping) else None
    output = output if isinstance(output, str) else ""
    return [_TERMINAL_ESCAPES.sub("", line) for line in output.splitlines()], ""


def _ready(
    action: str, record: dict[str, Any], path: Path, derived: Mapping[str, Mapping[str, Any]],
    children: list[dict[str, Any]], omh_home: Path, hermes_home: Path, now: float, shown: set[str] | None, *,
    task: str, say: str = "", settled: Mapping[str, Any] | None = None, budget: Mapping[str, int] | None = None,
    limits: dag_run.Limits = dag_run.DEFAULT_LIMITS, ignored: tuple[str, ...] = (), note: str = "",
) -> str:
    """``note`` is appended after every instruction the reply builds, so it never stands in for one of them."""
    slots = free_slots(hermes_home)
    if budget is not None:
        slots["oneshot"] = dict(budget)  # only in a one-shot session: an interactive payload is unchanged
    task_budget = _wave_budget(record, derived, budget, now, limits=limits)
    nodes = {str(node["id"]): node for node in record["nodes"]}
    # Each ready coding node goes to its chosen owner's fanout, never to delegate_task; checks and readers stay native.
    offered = dag_run.offerable(record, derived, now, limits=limits)
    exports, owner_say = _owner_exports(record, derived, offered)
    coding = [node_id for entry in exports for node_id in entry["nodes"]]
    # A run on a Docker or SSH terminal pins where its handoff files live before its first node goes out, and with no
    # terminal up to ask, hands out nothing yet.
    pinned, waits = False, ""
    if record.get("backend") in REMOTE_BACKENDS and "handoff_root" not in record and set(offered) - set(coding):
        root, waits = backend_root(task)
        if root is not None:
            record["handoff_root"] = root
            pinned = True
    # A run defined before the person turned isolation on: nothing goes to a child while it is on.
    isolated = not waits and _isolation_holds(record, offered, coding, hermes_home)
    calls, held = ([], []) if waits or isolated else dag_run.calls_for(
        record, derived, free_slots=slots["free"], per_call=slots["cap"], omh_home=omh_home, now=now, skip=coding,
        task_budget=task_budget, backend=delegation_backend(omh_home, hermes_home), limits=limits)
    # With the one-shot budget spent, a held node never gets a child: once nothing else is out, it is the parent's.
    spent_out = task_budget is not None and held and task_budget - sum(len(call["tasks"]) for call in calls) <= 0
    mine: list[str] = []
    if spent_out and not calls and not any(info["state"] in dag_run.LIVE for info in derived.values()):
        mine = list(held)
        for node_id in mine:
            attempt = dag_run.hand_out(nodes[node_id], derived[node_id]["state"], now)
            attempt["lane"] = "parent"
        held = []
    if calls or pinned or mine:
        record["updated_at"] = now
        dag_run.write_run(path, record)
        derived = dag_run.derive(record, children, now)
    extra: dict[str, Any] = {"calls": calls, "slots": slots}
    backend_say = _backend_say(calls)
    if backend_say:
        say = " ".join(part for part in (say, backend_say) if part)
    if held:
        extra["held_for_slots"] = held
    if mine:
        extra["for_parent"] = mine
    if settled:
        extra["settled"] = dict(settled)
    extra.update(_export_fields(exports))
    say = " ".join(part for part in (say, _export_say(exports), owner_say) if part)
    if action in ("define", "repair", "extend"):
        extra["topology"] = record["topology"]
        extra["lint"] = served_lint(record["lint"], omh_home, hermes_home)
    if mine:
        say = " ".join(part for part in (say, (
            f"The one-shot child budget is spent (delegation.oneshot_max_children is {budget['limit']}, "
            f"{budget['spent']} started), so no child can take {', '.join(mine)}. Do "
            f"{'it' if len(mine) == 1 else 'each'} yourself in this session, write "
            f"{'its handoff' if len(mine) == 1 else 'each handoff'} ("
            + "; ".join(f"{node_id}: {dag_run.node_handoff(record, omh_home, node_id)}" for node_id in mine)
            + "), and settle it; do not call delegate_task for it.")) if part)
    elif spent_out:
        # Added to whatever else the reply says (a provider-error retry's offer, for one): no child takes these.
        say = " ".join(part for part in (say, (
            f"The one-shot child budget has no child left for {', '.join(held)} "
            f"(delegation.oneshot_max_children is {budget['limit']}, {budget['spent']} started): dispatch the "
            "calls returned, settle the nodes out, and call ready again; the rest is then yours to do in this "
            "session.")) if part)
    if not say and held and not calls:
        say = "No delegate_task slot is free; end the turn and call ready again after a completion."
    if waits:
        instruction = TERMINAL_INTERRUPTED if waits == "interrupted" else TERMINAL_FIRST
        say = " ".join(part for part in (say, instruction.format(backend=record["backend"])) if part)
    elif isolated:
        say = " ".join(part for part in (say, WORKTREE_ISOLATION_HELD) if part)
    say = " ".join(part for part in (say, note) if part)
    return _result(action, record, derived, shown, say=say, extra=extra, now=now, limits=limits, ignored=ignored)


def _isolation_holds(record: Mapping[str, Any], offered: list[str], coding: list[str], hermes_home: Path) -> bool:
    """Whether a node `ready` would hand to `delegate_task` is held because each child would get its own worktree."""
    return bool(set(offered) - set(coding)) and worktree_isolation_on(hermes_home, str(record.get("backend") or ""))


def _backend_say(calls: list[dict[str, Any]]) -> str:
    """What the parent does with calls under a non-default Hermes delegation backend, or ``""``."""
    routes = [call["route"] for call in calls if "backend" in call["route"]]
    if not routes:
        return ""
    backend = routes[0]["backend"]
    if backend == "model_map":
        loose = sorted({route["category"] for route in routes if route.get("status") != "option_selected"})
        text = ("Hermes routes children with its model_map backend: do not call omh_delegate_route; pass the "
                "tasks unchanged, each with its `option`.")
        if loose:
            text += (f" No option of the user's runs {', '.join(loose)}: those tasks carry none and run on the "
                     "backend's default.")
        return text
    return (f"Hermes routes children with its {backend} backend, which OMH does not route: do not call "
            "omh_delegate_route, and pass the tasks unchanged.")


def served_lint(findings: list[str], omh_home: Path, hermes_home: Path) -> list[str]:
    """The run's lint as the parent reads it: `review_not_review_category` is dropped where Hermes' model_map backend
    offers no option for `review` but some for `unspecified-high`, so the advice never moves a node to a category the
    user's options cannot run. The stored record keeps the finding."""
    marker = "review_not_review_category:"
    if not any(finding.startswith(marker) for finding in findings):
        return findings
    options = (delegation_backend(omh_home, hermes_home) or {}).get("options") or {}
    if options.get("unspecified-high") and not options.get("review"):
        return [finding for finding in findings if not finding.startswith(marker)]
    return findings


def delegation_backend(omh_home: Path, hermes_home: Path) -> dict[str, Any] | None:
    """Hermes' delegation backend for `calls_for`; ``None`` under `default` (routes go through omh_delegate_route).

    Under `model_map` it carries each category's option names in chain
    order. Read-only: nothing in the user's config is written.
    """
    mode = read_backend_mode(hermes_home)
    if mode["backend"] == DEFAULT_BACKEND:
        return None
    routes, _status = load_model_provider_routes(omh_home)
    chains = effective_mixture_category_chains(omh_home, hermes_home)
    return {"backend": mode["backend"], "status": mode["status"],
            "options": category_options(mode, chains, routes)}


# The profile settings that move `dag_run.Limits`: `plugins.entries.omh.settings.<name>`, in seconds or a count.
DAG_LIMIT_SETTINGS = ("dag_stale_after_s", "dag_stuck_after_s", "dag_max_lost_reoffers")


def dag_limits(hermes_home: Path) -> tuple[dag_run.Limits, tuple[str, ...]]:
    """The run marks this profile sets, and the names of settings it wrote but this cannot use. Read-only.

    ``dag_stale_after_s``: how long a node no child took waits before ``ready``
    offers it again. ``dag_stuck_after_s``: how long a node may stay open before
    every view names it; ``0`` turns that off. ``dag_max_lost_reoffers``: how
    many times a node whose child a restart ended is offered again. A time
    mark under `dag_run.MIN_MARK_SECONDS` is raised to it, a count above
    `dag_run.MAX_LOST_REOFFERS_LIMIT` lowered to it; a value that is not a
    number, or a config this cannot read, keeps the default and is named.
    """
    try:
        text = (Path(hermes_home) / "config.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return dag_run.DEFAULT_LIMITS, ()
    except (OSError, UnicodeDecodeError):
        return dag_run.DEFAULT_LIMITS, DAG_LIMIT_SETTINGS
    values: dict[str, Any] = {}
    ignored: list[str] = []
    for name in DAG_LIMIT_SETTINGS:
        try:
            raw = runtime_paths.plugin_setting_text(text, name)
        except runtime_paths.RuntimeBindingError:
            return dag_run.DEFAULT_LIMITS, DAG_LIMIT_SETTINGS
        if raw is None:
            continue
        try:
            number = float(raw.strip())
        except ValueError:
            ignored.append(name)
            continue
        if number != number or number in (float("inf"), float("-inf")) or number < 0:
            ignored.append(name)
        elif name == "dag_max_lost_reoffers":
            values["max_lost_reoffers"] = min(int(number), dag_run.MAX_LOST_REOFFERS_LIMIT)
        elif name == "dag_stuck_after_s" and number == 0:
            values["stuck_after_s"] = 0.0
        else:
            values[name.removeprefix("dag_")] = max(number, dag_run.MIN_MARK_SECONDS)
    return dag_run.Limits(**values), tuple(ignored)


def _result(action: str, record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]],
            shown: set[str] | None, *, say: str = "", extra: Mapping[str, Any] | None = None,
            now: float | None = None, limits: dag_run.Limits = dag_run.DEFAULT_LIMITS,
            ignored: tuple[str, ...] = ()) -> str:
    now = time.time() if now is None else now
    state = dag_run.run_state(record, derived)
    payload: dict[str, Any] = {
        "schema_version": dag_run.DAG_RESULT_SCHEMA_VERSION,
        "action": action,
        "status": "ok",
        "run": record["run"],
        "name": record["name"],
        "goal": record.get("goal", ""),
        "state": state,
        "counts": dag_run.counts(record, derived),
        "status_line": dag_run.status_line(record, derived, added=dag_added_clause(record, derived, shown), now=now,
                                           limits=limits),
        "nodes": dag_run.node_rows(record, derived, now),
        "exports": [],
        "claim_boundary": dag_run.DAG_CLAIM_BOUNDARY,
    }
    if state == "needs_repair":
        payload["open"] = dag_run.open_failures(record, derived)
        say = say or ("A node failed: repair it (two cycles per node at most), or report what is open and cancel "
                      "the run.")
    elif state == "stopped":
        payload["open"] = dag_run.open_failures(record, derived)
        say = say or "The repair cycles are spent: report what is still open, and do not repair again."
    verdict, reasons = "", []
    if state in dag_run.FINISHED_STATES:
        # Whether a passing verify node covers the work (`dag_run.goal_verdict`): a done run may still be unverified.
        verdict, reasons = dag_run.goal_verdict(record, derived)
        payload["verdict"] = verdict
        payload["verdict_reasons"] = reasons
    if state == "done":
        left = dag_run.extend_rounds_left(record)
        payload["extend_rounds_left"] = left
        rounds = f"{left} round{'' if left == 1 else 's'} left"
        if verdict == "verified":
            say = say or (
                "Every node is accepted. Check each one against its SCOPE and the goal criteria: when work is "
                f"missing, extend the run ({rounds}); otherwise report the goal met."
                if left else
                "Every node is accepted and the extend rounds are spent. Check each one against its SCOPE and the "
                "goal criteria, then report the goal met or what is still open.")
        elif reasons == ["no_producers"]:
            say = say or (
                "Every node is accepted. No node wrote files, so nothing was built for a verify node to check: "
                "report what the nodes found, and the goal as unverified, not as met.")
        elif left:
            built = [str(node["id"]) for node in record["nodes"]
                     if dag_run.is_producer(node) and derived[str(node["id"])]["state"] != "superseded"]
            # A run of checks alone has no producer to name: the new node repeats the check and is read.
            what = (f"that depends on every producer ({', '.join(built)}) and checks the goal criteria" if built
                    else "that repeats the check and has its handoff read")
            say = say or (
                f"Every node is accepted, but the goal is unverified ({'; '.join(reasons)}). Add a role=verify node "
                f"with omh_dag action=extend {what} ({rounds}); until it passes, do not report the goal met.")
        else:
            say = say or (
                f"Every node is accepted, but the goal is unverified ({'; '.join(reasons)}) and the extend rounds "
                "are spent. Report the goal as unverified, with what is still open; do not report it met.")
    lost = dag_run.lost_for_good(record, derived, limits=limits)
    if lost:
        # Added to whatever else the reply says, on every action: nothing offers these nodes again.
        one = len(lost) == 1
        say = " ".join(part for part in (say, (
            f"Hermes restarted while {'node' if one else 'nodes'} {', '.join(lost)} ran, "
            f"{limits.max_lost_reoffers + 1} times, so {'it is' if one else 'they are'} not offered again: "
            f"settle {'it' if one else 'each'} failed or blocked.")) if part)
    found = dag_run.stuck(record, derived, now, limits=limits)
    if found:
        # Added to whatever else the reply says, on every action: a silent child gives no other signal.
        payload["stuck"] = [{"id": node_id, "open_for_s": int(age)} for node_id, age in found]
        say = " ".join(part for part in (say, dag_run.stuck_say(record, derived, found, limits)) if part)
    if limits != dag_run.DEFAULT_LIMITS or ignored:
        payload["limits"] = {"stale_after_s": limits.stale_after_s, "stuck_after_s": limits.stuck_after_s,
                             "max_lost_reoffers": limits.max_lost_reoffers}
        if ignored:
            payload["limits"]["ignored"] = list(ignored)
    if extra:
        payload.update(extra)
    if say:
        payload["say"] = say
    return json.dumps(payload, sort_keys=True)


def owner_choices(record: Mapping[str, Any]) -> tuple[str, ...]:
    """The external coding owners the request that defined this run named, sorted; () for any other run."""
    owners = record.get("owners")
    if not isinstance(owners, list):
        return ()
    return tuple(sorted({owner for owner in owners if owner in EXTERNAL_OWNERS}))


def _owner_exports(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]],
                   offered: list[str]) -> tuple[list[dict[str, Any]], str]:
    """Split ready coding nodes by their chosen owner; an unchosen node owner stays on delegate_task."""
    choices = owner_choices(record)
    nodes = {str(node["id"]): node for node in record["nodes"]}
    batches: dict[str, list[str]] = {}
    native = []
    for node_id in offered:
        node = nodes[node_id]
        if derived[node_id]["state"] != "ready" or not dag_run.is_coding(node) or "owner" not in node:
            continue
        owner = str(node["owner"])
        if owner in choices:
            batches.setdefault(owner, []).append(node_id)
        else:
            native.append(f"Node {node_id} names {owner}, which the request that defined this run did not name; "
                          "it runs on delegate_task.")
    return ([{"owner": owner, "nodes": batches[owner],
              "next": {"tool": "omh_dag", "action": "export", "owner": owner}} for owner in sorted(batches)],
            " ".join(native))


def _export_fields(exports: list[dict[str, Any]]) -> dict[str, Any]:
    """Always expose exports, retaining the old export object only for a single owner batch."""
    return {"exports": exports, **({"export": exports[0]} if len(exports) == 1 else {})}


def _export_say(exports: list[dict[str, Any]]) -> str:
    return " ".join(
        f"Coding nodes {', '.join(entry['nodes'])} go to {entry['owner']}, the coding owner the person chose: "
        f"call omh_dag action=export owner={entry['owner']} and run the commands it returns. "
        "The calls go to delegate_task as usual." for entry in exports)


def _flag(value: object) -> bool:
    """`provider_error` as given: a bool, or the words true and false; nothing else is read as either."""
    if value is None or isinstance(value, bool):
        return bool(value)
    if isinstance(value, str) and value.strip().casefold() in ("true", "false"):
        return value.strip().casefold() == "true"
    raise dag_run.DagRefusal("invalid_provider_error", "provider_error is true or false.")


def export_units(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], owner: str, *,
                 default_owner: str | None = None) -> list[dict[str, Any]]:
    """The coding nodes that can go to ``owner`` now, as `fanout_contract/v2` units.

    The ready coding nodes, and the waiting ones whose every open parent goes
    in the same owner's batch (the contract keeps their order). A coding node
    that waits on a native or another owner's node goes in a later batch,
    once that node settled.
    """
    # The pure helper keeps its legacy single-owner default; the tool passes the actual main-family choice (or "").
    default_owner = owner if default_owner is None else default_owner
    candidates = {str(node["id"]): node for node in record["nodes"]
                  if dag_run.is_coding(node) and node.get("owner", default_owner) == owner
                  and derived[str(node["id"])]["state"] in ("ready", "waiting")}
    chosen: set[str] = set()
    grew = True
    while grew:
        grew = False
        for node_id, node in candidates.items():
            if node_id not in chosen and all(parent in chosen or derived[parent]["state"] in dag_run.SATISFIED
                                             for parent in node["depends_on"]):
                chosen.add(node_id)
                grew = True
    exportable = [node for node in record["nodes"] if str(node["id"]) in chosen]
    if not exportable:
        raise dag_run.DagRefusal("nothing_to_export", "No coding node is ready for the coding owner yet.")
    units = []
    for node in exportable:
        units.append({
            "unit_id": str(node["id"]),
            "title": str(node["label"]),
            "owner": owner,
            "file_scope": list(node["write_scope"]),
            "depends_on": [parent for parent in node["depends_on"] if parent in chosen],
            "category": str(node["category"]),
        })
    return units


def export_goal(record: Mapping[str, Any], units: list[dict[str, Any]]) -> str:
    """The goal text frozen into the contract: the run's goal, then each unit's own instructions under its id."""
    prompts = {str(node["id"]): str(node["prompt"]) for node in record["nodes"]}
    lines = [f"dag-ulw run {record['name']}: {record.get('goal') or record['name']}",
             "Each unit's instructions follow under its unit id; do only your own unit's."]
    for unit in units:
        lines += ["", f"## {unit['unit_id']}", prompts[unit["unit_id"]]]
    return "\n".join(lines)


def _export(args: Mapping[str, object], record: dict[str, Any], path: Path,
            derived: Mapping[str, Mapping[str, Any]], children: list[dict[str, Any]], omh_home: Path,
            now: float, shown: set[str] | None, *, limits: dag_run.Limits = dag_run.DEFAULT_LIMITS,
            ignored: tuple[str, ...] = ()) -> str:
    owner = args.get("owner")
    if owner not in EXTERNAL_OWNERS:
        raise dag_run.DagRefusal("invalid_owner", f"Name the coding owner: {', '.join(EXTERNAL_OWNERS)}.")
    if owner not in owner_choices(record):
        raise dag_run.DagRefusal(
            "owner_not_chosen",
            "The request that defined this run did not name this coding owner, so its nodes run on delegate_task. "
            "A choice counts only for the request it was made in: the person names the owner in a new dag-ulw "
            "request.",
        )
    units = export_units(record, derived, str(owner), default_owner="")
    payload: dict[str, Any] = {"units": units}
    if len(units) > SPAWN_PLAN_THRESHOLD:
        plan = args.get("spawn_plan")
        if not isinstance(plan, Mapping) or any(not str(plan.get(field) or "").strip() for field in SPAWN_PLAN_FIELDS):
            raise dag_run.DagRefusal(
                "spawn_plan_required",
                f"{len(units)} units need a spawn_plan answering {', '.join(SPAWN_PLAN_FIELDS)}.")
        payload["spawn_plan"] = {field: str(plan[field]) for field in SPAWN_PLAN_FIELDS}
    goal = export_goal(record, units)
    fanout_id = "fanout-" + hashlib.sha256(" ".join(goal.split()).encode("utf-8")).hexdigest()[:12]
    folder = dag_run.handoff_path(omh_home, str(record["session_id"]), str(record["run"]), "x").parent
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Named for the fanout: a later export of the same run must not overwrite one whose commands have not run yet.
    units_file, goal_file = folder / f"{fanout_id}-units.json", folder / f"{fanout_id}-goal.txt"
    units_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    goal_file.write_text(goal + "\n", encoding="utf-8")
    for unit in units:
        node = next(item for item in record["nodes"] if item["id"] == unit["unit_id"])
        attempt = dag_run.hand_out(node, derived[unit["unit_id"]]["state"], now)
        attempt["lane"] = "fanout"
    record["updated_at"] = now
    dag_run.write_run(path, record)
    derived = dag_run.derive(record, children, now)
    offered = dag_run.offerable(record, derived, now, limits=limits)
    exports, owner_say = _owner_exports(record, derived, offered)
    say = " ".join(part for part in (
        f"These nodes go to {owner} through the fanout bridge; run the commands it returns, then settle each node "
        "from the fanout result.", _export_say(exports), owner_say) if part)
    return _result("export", record, derived, shown, say=say, extra={
        **_export_fields(exports),
        "fanout": {
            "owner": owner, "fanout_id": fanout_id, "units_file": str(units_file), "goal_file": str(goal_file),
            "commands": export_commands(str(owner), units, fanout_id, units_file, goal_file),
        },
    }, now=now, limits=limits, ignored=ignored)


def export_commands(owner: str, units: list[dict[str, Any]], fanout_id: str, units_file: Path,
                    goal_file: Path) -> list[str]:
    """The commands that dispatch one export. `fanout prepare` freezes no contract for a single unit (it answers
    `redirect_to_run`), so a one-node batch, the usual case once each owner exports its own nodes, goes through
    `omh coding run` with the same goal file instead."""
    if len(units) == 1:
        unit = units[0]
        scope = " ".join(f"--file-scope {shlex.quote(path)}" for path in unit["file_scope"])
        return [f"omh coding run --owner {owner} --unit-id {shlex.quote(unit['unit_id'])} {scope} "
                f"--goal-file {shlex.quote(str(goal_file))} --repo-root ."]
    return [
        f'omh coding fanout prepare --goal "$(cat {goal_file})" --units {units_file} --record',
        f"omh coding fanout dispatch {fanout_id} --goal-file {goal_file} --repo-root .",
    ]


def _refused(action: str, reason: str, say: str, *, detail: str = "") -> str:
    payload: dict[str, object] = {"schema_version": dag_run.DAG_RESULT_SCHEMA_VERSION, "action": action,
                                  "status": "refused", "reason": reason, "say": say, "exports": []}
    if detail:
        payload["detail"] = detail
    return json.dumps(payload, sort_keys=True)


# Module scope, not call time (#1979), and guarded so a host missing one still registers the tool (#1623).
try:
    from .. import kanban_board_reader as _kanban_board_reader
    from .. import runtime_reader as _runtime_reader
    from ..hooks import nudge_budget as _nudge_budget
except ImportError as _bundle_import_error:
    _BUNDLE_IMPORT_FAILURE = _bundle_import_error.name or "unknown"
else:
    _BUNDLE_IMPORT_FAILURE = ""
