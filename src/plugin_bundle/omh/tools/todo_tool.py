from __future__ import annotations

from .. import runtime_paths

import json
from pathlib import Path
from typing import Any

from ..host_observation import (
    OBSERVATION_SCHEMA,
    attach_public_observation,
    host_session_id,
    observe_plugin_tool_call,
)
from ..dispatch_outcomes import _parse_timestamp
from ..native_tools import NATIVE_CANCELLED_REASON, NATIVE_TODO_TOOL, OMH_TODO_HELD_PLANS, native_tool_presence_clause
from ..orchestration_say import todo_say, with_say
from ..runtime_reader import default_omh_home, read_omh_todo
from ..todo_evidence import observed_calls
from ..todo_reconciliation import unverified_done_items
from ..todo_store import (
    TODO_CLAIM_BOUNDARY,
    TODO_ITEM_STATES,
    TODO_PLAN_STAGES,
    TodoContendedError,
    TodoStoreError,
    TodoValidationError,
    advance_todo_item,
    bind_done_items,
    build_todo_record,
    clear_todo,
    dropped_bindings,
    read_todo_record,
    todo_timestamp,
    write_todo,
)
from ..todo_templates import CODE_STORY_TEMPLATE
from ..completion_store import completion_action

_COMPLETION_FIELDS = {
    "checkpoint_id": {"type": "string", "description": "ID returned by checkpoint; recall without it lists this profile/project's dossiers."},
    "accepted": {"type": "boolean", "description": "checkpoint only: the person accepted exactly the current todo scope. Not a host approval or permission grant."},
    "rejected": {"type": "array", "items": {"type": "string"}, "maxItems": 20,
                 "description": "checkpoint: short summaries of rejected ideas, kept outside accepted scope; no transcript."},
    "revision": {"type": "string", "maxLength": 128,
                 "description": "Required for checkpoint, record and keyed recall: exact revision/worktree fingerprint claimed or checked. Caller-declared, not host-attested."},
    "environment": {"type": "string", "maxLength": 128,
                    "description": "Required with revision: environment/toolchain fingerprint; a change makes old results stale. Never environment values or secrets."},
    "result": {
        "type": "object", "additionalProperties": False,
        "description": "record: one verification verdict, review finding set or QA result for one frozen item. No logs, prompts, transcripts or raw command output; provenance is claimed, never attested by storage.",
        "properties": {
            "kind": {"type": "string", "enum": ["verification", "review", "qa"]},
            "item": {"type": "integer", "minimum": 1},
            "verdict": {"type": "string", "enum": ["PASS", "HOLD", "BLOCK"]},
            "summary": {"type": "string", "maxLength": 200},
            "findings": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 20},
            "claimed_source": {"type": "string", "enum": ["model", "host_exit", "independent_review", "ci"]},
            "claimed_evidence_state": {"type": "string", "enum": ["prepared_not_observed", "observed"]},
            "references": {"type": "array", "maxItems": 8, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"type": {"type": "string", "enum": ["verification_receipt/v1", "artifact", "ci_run"]},
                               "id": {"type": "string", "maxLength": 128}},
                "required": ["type", "id"]}},
        },
        "required": ["kind", "item", "verdict", "summary", "findings", "claimed_source", "claimed_evidence_state", "references"],
    },
}

# Longer guidance for this tool lives in the `todo-checklist` skill's
# references: `checklist-discipline.md` (phases, outcomes, blocked_reason vs
# deferred_reason, advance vs set) and `closing-a-story.md` (checkpoint,
# record, recall). This schema is sent with every request that carries the
# tool, so it keeps the rules a model needs to drive the list to its stop
# without that skill loaded, and not the reasons behind them.
#
# The second sentence is the one-checklist rule (`native_todo`): steps live in
# exactly one tool. Hermes' native todo_list holds them wherever the presence
# rule finds it, and OMH mirrors it into this record, so this tool is then
# called only for what todo_list cannot say. A planning run, an accepted plan
# (whose stage and `check:` items `omh_team` binds lanes to) and a code-story
# template keep their steps here, because `plan_stage` and the template exist
# only on this tool.
OMH_TODO_SCHEMA = {
    "name": "omh_todo",
    "description": (
        "Declare, advance, clear, or read this session's metadata-only plan todo list, which the OMH HUD "
        "renders above the prompt; other sessions neither see nor overwrite it. "
        f"Keep steps in ONE tool, never both: {OMH_TODO_HELD_PLANS} keeps them here "
        "(to leave one for unrelated work, clear it first; a deferred_reason only pauses it); "
        f"otherwise, when {native_tool_presence_clause(NATIVE_TODO_TOOL)}, keep them in {NATIVE_TODO_TOOL} "
        "(OMH mirrors each write into this plan) and call this tool only for checkpoint/record/recall, "
        "blocked_reason, deferred_reason, or advancing a done item again after its check passes. "
        "When steps live here, declare them BEFORE starting engine work (todo init): numbered phases in delivery order covering setup, "
        "implement/verify/deliver per work unit, independent review, and an evidence-and-cleanup close, "
        "one item per observable outcome. Keep exactly one item active and advance it as work completes. "
        "Items are plan declarations, never execution evidence. "
        "To finish or resume accepted work, read the plan and recall its checkpoint; do exactly the "
        "accepted items, never rejected ideas. No action executes work or grants approval; templates are "
        "optional and tiny tasks need fewer phases. "
        "Relay any `say` field to the user once, in their language and your own words."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            **_COMPLETION_FIELDS,
            "action": {
                "type": "string",
                "enum": ["set", "advance", "clear", "show", "checkpoint", "record", "recall"],
                "description": (
                    "set writes the whole list: items left out are dropped. advance changes one item; "
                    "clear removes the list; show reads it. Change a state with advance, not set. "
                    "checkpoint freezes the accepted scope; record appends a result declaration; "
                    "recall reads scope and declarations across sessions without resuming work, "
                    "and comes before reporting completion."
                ),
            },
            "title": {
                "type": "string",
                "description": "Optional plan title for the todo panel header.",
            },
            "template": {
                "type": "string",
                "enum": [CODE_STORY_TEMPLATE],
                "description": (
                    "For action=set: 'code-story' is the ten phases I. Story through X. Close, "
                    "for a change the person asks to carry from story to close. With no items the "
                    "ten are declared for you. Re-send it on a later set: every write must cover "
                    "all ten, and an unneeded phase is kept as state=done with a blocked_reason, "
                    "never dropped. "
                    "Omit this field for an ordinary plan."
                ),
            },
            "plan_stage": {
                "type": "string",
                "enum": list(TODO_PLAN_STAGES),
                "description": (
                    "For action=set on a PLANNING run (ralplan, plan, deep-interview) only. "
                    "'awaiting_acceptance' when declaring the planning checklist: while it holds, "
                    "write_file or patch in this session goes to the human-approval gate. "
                    "'accepted' once the person gives an explicit go-ahead in this conversation, "
                    "ending that. Omit it for a delivery or execution plan, which is never gated. "
                    "advance carries it forward; a set without it drops it."
                ),
            },
            "deferred_reason": {
                "type": "string",
                "description": (
                    "Omit this field unless the PERSON redirected this session away from the plan "
                    "('do Y first', 'forget that for now'); name what they asked for instead. "
                    "Sent with set or advance. While it holds, the plan stops asking you to advance "
                    "the next item. It CLEARS ITSELF: it is bound to the item list sent with it, so "
                    "the next write that omits it, or any item change that does not re-send it, ends "
                    "it. Re-send it with a changed list only while the person is still steering. "
                    "It is not blocked_reason, which is per item for work that CANNOT proceed and "
                    "wins when both apply."
                ),
            },
            "item": {
                "type": "integer",
                "minimum": 1,
                "description": "For action=advance: which item to change, 1 for the first.",
            },
            "item_text": {
                "type": "string",
                "description": (
                    "For action=advance: the start of that item's current text; a mismatch "
                    "(stale index) is refused."
                ),
            },
            "state": {
                "type": "string",
                "enum": list(TODO_ITEM_STATES),
                "description": "For action=advance: the item's new state.",
            },
            "blocked_reason": {
                "type": "string",
                "description": (
                    "For action=advance: items[].blocked_reason for the changed item; omitting it "
                    "clears one."
                ),
            },
            "items": {
                "type": "array",
                "description": "Todo items for action=set, in display order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Item text."},
                        "state": {
                            "type": "string",
                            "enum": ["pending", "active", "done"],
                            "description": "Defaults to pending.",
                        },
                        "phase": {
                            "type": "string",
                            "description": (
                                "Optional phase label numbered in delivery order, e.g. 'I. Bootstrap'. "
                                "Items sharing a phase render as one section."
                            ),
                        },
                        "blocked_reason": {
                            "type": "string",
                            "description": (
                                "Omit this field unless the item CANNOT proceed; name what it waits on "
                                "(a review, an approval, a missing credential, another item). Any value "
                                "stops the plan advancing past this item, so an unstarted, slow or "
                                "mid-work item carries none, nor one whose text merely discusses "
                                "blocking. Remove it once the thing it names arrives."
                            ),
                        },
                        "depth": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 3,
                            "description": (
                                "Optional nesting: 0 = top-level; 1-3 render as subtasks under the "
                                "preceding shallower item and may omit phase."
                            ),
                        },
                    },
                    "required": ["text"],
                },
            },
            "omh_home": {
                "type": "string",
                "description": "Standalone operator override for action=show only; writes reject it. Native Hermes calls reject this field; omit it to use the active profile.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
        "required": ["action"],
    },
}


def omh_todo_handler(args: dict[str, Any], **kwargs) -> str:
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observation = observe_plugin_tool_call("omh_todo", args, kwargs)
    # Hermes passes its stable session/thread id as a keyword on every tool
    # call, so a plan declared in chat is stored for, and read back for, the
    # session that declared it. A host that supplies none leaves this empty:
    # the record is the home-wide one, exactly like a CLI write.
    session_ref = host_session_id(kwargs)
    home_arg = str(args.get("omh_home", "") or "")
    action = str(args.get("action", ""))
    if action in {"checkpoint", "record", "recall"}:
        return json.dumps(attach_public_observation(
            completion_action(args, session=session_ref), observation), sort_keys=True)
    payload: dict[str, Any] = {
        "schema_version": "omh_todo_result/v1",
        "action": action,
        "claim_boundary": TODO_CLAIM_BOUNDARY,
    }
    # Mutations bind to the environment-configured home only: a caller-chosen
    # path would turn this metadata tool into an arbitrary-location
    # file-create/delete primitive.
    if action in {"set", "advance", "clear"} and home_arg:
        payload["status"] = "invalid_todo"
        payload["error"] = "omh_home override is read-only; set and clear use the configured OMH home"
        payload["todo"] = read_omh_todo(session_ref=session_ref)
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if action == "set":
        try:
            items = args.get("items")
            dropped: list[dict[str, str]] = []
            if isinstance(items, list):
                prior = read_todo_record(default_omh_home(), session_ref) or {}
                items, dropped = bind_declared_items(items, prior, session_ref)
            record = build_todo_record(
                args.get("title", ""),
                items,
                source="omh_todo",
                session_ref=session_ref,
                deferred_reason=args.get("deferred_reason", ""),
                template=args.get("template", ""),
                plan_stage=args.get("plan_stage", ""),
                dropped=dropped,
            )
            write_todo(default_omh_home(), record)
            payload["status"] = "written"
        # Before the generic branch, and it is not a nicety. `invalid_todo`
        # tells a writer its payload was wrong, and a writer that believes
        # that rewrites the list it just sent -- the whole-list rewrite this
        # action exists to stop -- when the record is simply busy for a few
        # milliseconds and the same call would land.
        except TodoContendedError as error:
            payload["status"] = "contended"
            payload["error"] = str(error)
        except (TodoValidationError, TodoStoreError) as error:
            payload["status"] = "invalid_todo"
            payload["error"] = str(error)
    elif action == "advance":
        # Same store call, same validator, same stamp as `set` above: the
        # single-item path is a narrower way to reach one write, never a
        # second way to write a record.
        try:
            advanced = advance_todo_item(
                default_omh_home(),
                item=args.get("item"),
                item_text=args.get("item_text", ""),
                state=args.get("state", ""),
                source="omh_todo",
                session_ref=session_ref,
                blocked_reason=args.get("blocked_reason", ""),
                deferred_reason=args.get("deferred_reason", ""),
                observed_calls=lambda opened, held: _calls_since(
                    session_ref, opened, held, todo_timestamp()
                ),
            )
            payload["status"] = "written"
            # On a plan todo_list holds the store keeps todo_list's state
            # (`advance_todo_item`); a writer that asked for another one is
            # told, rather than left to read "written" as the move it wanted.
            kept = _state_kept(advanced, args.get("item"), args.get("state"))
            if kept:
                payload["state_kept"] = kept
        except TodoContendedError as error:
            payload["status"] = "contended"
            payload["error"] = str(error)
        except (TodoValidationError, TodoStoreError) as error:
            payload["status"] = "invalid_todo"
            payload["error"] = str(error)
    elif action == "clear":
        try:
            payload["status"] = (
                "cleared" if clear_todo(default_omh_home(), session_ref) else "already_absent"
            )
        except TodoStoreError as error:
            payload["status"] = "invalid_todo"
            payload["error"] = str(error)
    elif action == "show":
        payload["status"] = "read"
    else:
        payload["status"] = "invalid_action"
        payload["error"] = 'action must be set, advance, clear, show, checkpoint, record, or recall'
    payload["todo"] = read_omh_todo(runtime_paths.plugin_home(home_arg), session_ref=session_ref)
    # What the stop criterion reads for this plan, returned where the writer
    # can act on it: each done item no recorded fact closes, with the reason.
    # Omitted when there is none, so a plan without one reads as it did.
    unverified = _unverified(payload["todo"], session_ref)
    if unverified:
        payload["done_unverified"] = unverified
    with_say(
        payload,
        todo_say(action, payload["status"], payload["todo"], item=args.get("item"), unverified=unverified),
    )
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def bind_declared_items(
    items: list[Any],
    prior: dict[str, Any],
    session_ref: str,
    *,
    hermes_home: Path | None = None,
) -> tuple[Any, list[dict[str, str]]]:
    """``items`` bound the way a whole-list write binds them, and the plan's dropped bindings.

    OMH binds items itself and ignores any binding the writer sent
    (`bind_done_items`). Each item is judged over its own window; a new
    item's opens at this write. A binding no item of the new list continues
    is kept on the plan (`dropped_bindings`): a rename or a split must not
    carry work past the check that failed under its old name.

    Shared by `omh_todo action=set` and the native `todo_list` projection
    (`native_todo`), so a done mark is judged the same way whichever tool
    wrote it. ``prior`` is the stored record (``{}`` when none);
    ``hermes_home`` is the host home whose session records name the calls,
    resolved from the plugin binding when omitted.
    """
    now = todo_timestamp()
    prior_stamp = prior.get("updated_at")
    fallback_start = (
        prior_stamp if isinstance(prior_stamp, str) and _parse_timestamp(prior_stamp) else now
    )
    calls = (
        _calls_since(
            session_ref,
            _earliest_window(prior.get("items"), fallback_start),
            set(),
            now,
            hermes_home=hermes_home,
        )
        if _declares_done(items)
        else []
    )
    dropped = dropped_bindings(
        items,
        prior_items=prior.get("items"),
        prior_dropped=prior.get("dropped_bindings"),
        now=now,
    )
    bound = bind_done_items(
        items,
        prior_items=prior.get("items"),
        calls=calls,
        fallback_start=fallback_start,
        now=now,
    )
    return bound, dropped


# The record's states in the words todo_list uses, which are the ones the
# model sees on a plan todo_list holds.
_NATIVE_STATUS_OF_STATE = {"pending": "pending", "active": "in_progress", "done": "completed"}


def _state_kept(record: object, item: object, requested: object) -> str:
    """The note for an advance whose state todo_list kept, or ``""``."""
    if not isinstance(record, dict) or record.get("source") != NATIVE_TODO_TOOL:
        return ""
    items = record.get("items")
    if not isinstance(items, list) or isinstance(item, bool) or not isinstance(item, int):
        return ""
    if not 1 <= item <= len(items) or not isinstance(items[item - 1], dict):
        return ""
    entry = items[item - 1]
    stored = entry.get("state")
    if stored not in _NATIVE_STATUS_OF_STATE or stored == requested:
        return ""
    status = (
        "cancelled"
        if entry.get("blocked_reason") == NATIVE_CANCELLED_REASON
        else _NATIVE_STATUS_OF_STATE[stored]
    )
    return f"todo_list sets item states on this plan; item {item} stays {status}"


def _declares_done(items: object) -> bool:
    return isinstance(items, list) and any(
        isinstance(item, dict) and item.get("state") == "done" for item in items
    )


def _calls_since(
    session_ref: str, stamp: object, held: set[str], until: str, *, hermes_home: Path | None = None
) -> list[dict[str, Any]]:
    """The calls this session recorded in ``(stamp, until]`` that ``held`` does not hold.

    Oldest first, as `todo_evidence.observed_calls` returns them. An
    unparseable ``stamp`` is no window and binds nothing; ``until`` is the
    done write's own stamp, so a call can never be bound to a done mark made
    before it was recorded. A host that cannot bind its home has no records
    to name, the same answer as a session that ran nothing.
    """
    start = _parse_timestamp(stamp) if isinstance(stamp, str) and stamp else None
    end = _parse_timestamp(until)
    if start is None or end is None:
        return []
    if hermes_home is None:
        try:
            hermes_home = runtime_paths.plugin_home(None, hermes=True)
        except (runtime_paths.RuntimeBindingError, OSError, RuntimeError):
            return []
    return observed_calls(
        hermes_home,
        session_ref,
        after_epoch=start.timestamp(),
        until_epoch=end.timestamp(),
        exclude=held,
    )


def _earliest_window(items: object, fallback: str) -> str:
    """The earliest window any stored item opens, so one read covers every item's."""
    earliest = fallback
    earliest_at = _parse_timestamp(fallback)
    for item in items if isinstance(items, list) else []:
        stamp = item.get("window_start") if isinstance(item, dict) else None
        parsed = _parse_timestamp(stamp) if isinstance(stamp, str) else None
        if parsed is not None and (earliest_at is None or parsed < earliest_at):
            earliest, earliest_at = stamp, parsed
    return earliest


def _unverified(todo: object, session_ref: str) -> list[dict[str, Any]]:
    try:
        hermes_home = str(runtime_paths.plugin_home(None, hermes=True))
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError):
        hermes_home = ""
    if not isinstance(todo, dict):
        return []
    return [
        {key: entry[key] for key in ("item", "state", "reason")}
        for entry in unverified_done_items(todo, hermes_home=hermes_home, session_ref=session_ref)
    ]
