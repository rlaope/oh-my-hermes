from __future__ import annotations

import json
from typing import Any

from .. import runtime_paths
from ..host_observation import (
    attach_public_observation,
    host_session_id,
    observe_plugin_tool_call,
)
from ..loop_bridge import LOOP_TOOL_ACTIONS, run_loop_tool_action
from ..orchestration_say import loop_say, with_say

# Enum members restated from OMH core so the schema is available on a host with
# no installed `omh` package. `tests/test_loop_tool.py` pins each tuple against
# its producer in `omh.workflows.goal_loop`.
_PERMISSION_PROFILES = ("observe_only", "handoff_only", "execute_with_gates", "full_loop", "custom")
_LOOP_ACTIONS = (
    "research",
    "planning",
    "ultragoal_creation",
    "executor_handoff",
    "executor_dispatch",
    "repo_edit",
    "pr_creation",
    "pr_revision",
    "review_fix_loop",
    "ci_fix_loop",
    "release_note_work",
    "external_posting_prep",
    "external_posting",
    "merge",
)
_EXECUTOR_OPTION_IDS = ("choose", "codex", "claude-code", "generic", "omx-runtime", "hermes")


def _strings(description: str, *, enum: tuple[str, ...] = ()) -> dict[str, Any]:
    items: dict[str, Any] = {"type": "string"}
    if enum:
        items["enum"] = list(enum)
    return {"type": "array", "items": items, "description": description}


OMH_LOOP_SCHEMA = {
    "name": "omh_loop",
    "description": (
        "Manage one durable OMH Loop. It is permission-scoped (loop_cycle/v2), for this session, without "
        "shell commands. Every mutation binds to the configured OMH home and this host session; no "
        "argument selects a store. A successful call records an OMH transition only: never executor "
        "dispatch, implementation, review, CI, merge readiness, or merge, and a queue item OMH "
        "prepares stays prepared_not_observed until separate evidence is recorded. Each action "
        "accepts only the fields marked with its name below; a field from another action is "
        "refused, not ignored. Tick, sticky rules, queue dispatch and recovery, driver binding and "
        "migration, handoffs, and narration stay on the `omh loop` CLI. "
        "Relay any `say` field to the user once, in their language and your own words."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(LOOP_TOOL_ACTIONS),
                "description": (
                    "assess classifies whether a goal is loopable before any loop exists (needs "
                    "message). start creates one loop (needs goal_summary, goal_reframe, "
                    "success_criteria). status reads one loop's card, or lists every loop without "
                    "loop_id. feedback records one cycle's observed artifacts, internal gap, or "
                    "external wait. permit widens or narrows the authority envelope. run_once takes "
                    "at most one legal advancement and reports why when it takes none. "
                    "goal_driver_observe records one driver observation. queue_observe records "
                    "observed evidence against a prepared queue item (needs queue_id and "
                    "evidence_refs). Every action but assess, start, and status needs loop_id and "
                    "expected_revision."
                ),
            },
            "loop_id": {
                "type": "string",
                "description": "The loop to act on. Omit on status to list every loop.",
            },
            "expected_revision": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "The record_revision action=status last reported. Required for every "
                    "mutation except start; refused as stale, not applied, when the loop has "
                    "moved on, so a retry or another session cannot overwrite an unseen change."
                ),
            },
            "mutation_id": {
                "type": "string",
                "description": (
                    "Caller-chosen id that makes a retried mutation replay its original result "
                    "instead of applying twice."
                ),
            },
            "message": {
                "type": "string",
                "description": "assess: the goal text to classify. Metadata only, no transcripts.",
            },
            "include_goal": {
                "type": "boolean",
                "description": "assess: echo the goal text back in the assessment.",
            },
            "goal_summary": {
                "type": "string",
                "description": "start: the goal as the user stated it.",
            },
            "goal_reframe": {
                "type": "string",
                "description": "start: the bounded first loop goal this loop will actually work on.",
            },
            "success_criteria": _strings(
                "start: observable criteria that would end this loop. At least one."
            ),
            "permission_profile": {
                "type": "string",
                "enum": list(_PERMISSION_PROFILES),
                "description": "start: the authority envelope profile. Defaults to handoff_only.",
            },
            "allowed_executors": _strings(
                "start and permit: executors this loop may hand off to."
            ),
            "allow_actions": _strings(
                "start and permit: loop actions to allow.", enum=_LOOP_ACTIONS
            ),
            "forbid_actions": _strings(
                "start and permit: loop actions to forbid. Forbid always wins over allow.",
                enum=_LOOP_ACTIONS,
            ),
            "linked_goal_id": {
                "type": "string",
                "description": "start: an existing goal ledger id to bind completion evidence to.",
            },
            "allow_unloopable": {
                "type": "boolean",
                "description": (
                    "start: create loop state even when the loopability assessment recommends "
                    "another surface. An explicit override, not a default."
                ),
            },
            "executor": {
                "type": "string",
                "enum": list(_EXECUTOR_OPTION_IDS),
                "description": "start: the driver executor selection. Defaults to hermes.",
            },
            "work_kind": {
                "type": "string",
                "enum": ["coding", "non_coding"],
                "description": "start: the driver work kind. Defaults to non_coding.",
            },
            "executor_session_ref": {
                "type": "string",
                "description": "start: executor session reference for the selected driver.",
            },
            "observed_artifacts": _strings(
                "feedback: references to artifacts already observed this cycle."
            ),
            "internal_gap": {
                "type": "string",
                "description": "feedback: the one actionable gap the loop can close locally.",
            },
            "external_wait": {
                "type": "string",
                "description": "feedback: what the loop is waiting on outside itself.",
            },
            "context_exhausted": {
                "type": "boolean",
                "description": "feedback: checkpoint because the working context ran out.",
            },
            "budget_exhausted": {
                "type": "boolean",
                "description": "feedback: checkpoint because the budget ran out.",
            },
            "driver_observation": {
                "type": "object",
                "description": (
                    "goal_driver_observe: the bounded driver observation object. Metadata and "
                    "evidence references only, never raw transcripts or provider payloads."
                ),
            },
            "queue_id": {
                "type": "string",
                "description": "queue_observe: the prepared queue item being observed.",
            },
            "evidence_refs": _strings(
                "queue_observe: references to the observed evidence. At least one."
            ),
            "worktree_evidence_refs": _strings("queue_observe: worktree evidence references."),
            "subagent_evidence_refs": _strings("queue_observe: subagent evidence references."),
            "connector_evidence_refs": _strings("queue_observe: connector evidence references."),
            "dispatch_attempt_id": {
                "type": "string",
                "description": "queue_observe: the dispatch attempt this observation closes.",
            },
            "summary": {
                "type": "string",
                "description": "queue_observe: short metadata-only summary of what was observed.",
            },
        },
        "required": ["action"],
    },
}

# What the plugin-invocation observer is allowed to read out of this tool's
# arguments. The shared reader also picks up `message` and `evidence_refs` when
# they are present, and for this tool those are Loop inputs -- a goal the user
# typed, and references belonging to the loop's own evidence ledger -- not host
# metadata about the call. Two ledgers, and neither should be filled from the
# other.
#
# Only the nested block: the reader's top-level `host` / `session_id` /
# `source` fallbacks cannot reach this tool, because the bridge refuses any
# argument that is neither an envelope argument nor a field of the requested
# action, and none of those three is either. That is the intended result --
# a model-supplied `session_id` must never stand in for the host's.
_OBSERVER_ARG_KEYS = ("observation",)


def omh_loop_handler(args: dict[str, Any], **kwargs) -> str:
    # Rejected before any observer or reader touches the filesystem: this tool
    # accepts no home field at all, on any host. Loop mutations are the state a
    # caller-chosen root would most obviously be abused to plant.
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observer_args = {key: args[key] for key in _OBSERVER_ARG_KEYS if key in args}
    observation = observe_plugin_tool_call("omh_loop", observer_args, kwargs)
    request = {key: value for key, value in args.items() if key != "observation"}
    payload = run_loop_tool_action(request, session_ref=host_session_id(kwargs))
    payload["plugin_tool"] = "omh_loop"
    with_say(payload, loop_say(request, payload))
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
