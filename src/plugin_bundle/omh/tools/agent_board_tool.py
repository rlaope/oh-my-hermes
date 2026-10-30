"""Prepare/status only. Native tools are invoked exclusively by Hermes' loop."""
from __future__ import annotations

from collections.abc import Mapping
import json

from ..orchestration_say import board_say, with_say

# Bound when Hermes imports this module, not on each call. Hermes may drop a
# plugin's modules from `sys.modules` while the handler it registered stays
# live (its loader evicts `hermes_plugins.<slug>.*` on a reload or a failed
# load), and a relative import made at call time then has no parent package
# to resolve against. Tools that hold their siblings from module scope keep
# working in that state; this one looked the bridge up per call and reported
# the board core missing on a host that had it (#1979).
# The guard stays: a host without the bridge must still register this tool
# and report the absence instead of failing to load (#1623).
try:
    from .. import agent_board_bridge as _bridge_module
except ImportError as exc:
    _bridge_module = None
    _BRIDGE_IMPORT_FAILURE = exc.name or "agent_board_bridge"
else:
    _BRIDGE_IMPORT_FAILURE = ""

# The engine's closed prepare shape. The handler names a missing field before
# the engine runs, because the engine's own refusal reaches the caller only as
# the opaque `invalid_request_or_board_store` (#2277).
_PREPARE_ONLY_FIELDS = ("coordination", "operation", "board", "profile", "arguments")
PREPARE_REQUIRED_FIELDS = ("action", "request_id", *_PREPARE_ONLY_FIELDS)

OMH_AGENT_BOARD_SCHEMA = {
    "name": "omh_agent_board",
    "description": "Prepare or inspect a native Kanban action. prepare builds a durable action; status reads its metadata-only receipt. Preparation is not authorization or execution; invoke the returned native tool through Hermes' normal tool loop. A durable create may state lane_role (builder, verifier, reviewer, docs or qa): OMH fills that lane's skills and workspace_kind from the role, refuses a verifier or reviewer that declares no parents, and removes the role before the native action. Bounded child research uses delegation instead. prepare needs coordination, operation, board, profile and arguments; status takes only request_id. No uploads, downloads, dispatch or JSON grants. Relay any `say` field to the user once, in their language and your own words.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["prepare", "status"]},
            "request_id": {"type": "string"},
            "coordination": {"type": "string", "enum": ["durable", "bounded_research"]},
            "operation": {"type": "string"},
            "board": {"type": "string"},
            "profile": {"type": "string", "description": "Host profile being coordinated."},
            "arguments": {"type": "object"},
            "task_id": {"type": "string"},
            "expected_observation_ref": {"type": "string"},
        },
        "required": ["action", "request_id"],
        "additionalProperties": False,
        # Hermes removes a top-level combinator from every tool schema before
        # any provider sees it (tools/schema_sanitizer.py), so the description
        # states the prepare fields too.
        "oneOf": [
            {"properties": {"action": {"const": "status"}}, "maxProperties": 2},
            {"properties": {"action": {"const": "prepare"}}, "required": list(_PREPARE_ONLY_FIELDS)},
        ],
    },
}


def omh_agent_board_handler(args: Mapping[str, object], **kwargs: object) -> str:
    module = _bridge_module
    if module is None:
        return _unavailable("omh_agent_board_core_unavailable",
                            detail=f"board_bridge_unimportable:{_BRIDGE_IMPORT_FAILURE}")
    # A bridge Hermes could not exec can sit in `sys.modules` as a stub with
    # none of its names (#1623); taking the names by attribute keeps that a
    # missing component rather than an AttributeError.
    try:
        BoardCoreUnavailable = module.BoardCoreUnavailable
        handler_identity = module.handler_identity
        host_capabilities = module.host_capabilities
        installed_bridge = module.installed_bridge
        installed_status = module.installed_status
    except AttributeError:
        return _unavailable("omh_agent_board_core_unavailable", detail="board_bridge_incomplete")
    try:
        identity = handler_identity(args, kwargs)
        if args.get("action") == "status":
            if set(args) != {"action", "request_id"} or not isinstance(args.get("request_id"), str):
                return _unavailable("invalid_status_input")
            return json.dumps(installed_status(str(args["request_id"])), sort_keys=True)
        board = args.get("board")
        if not isinstance(board, str):
            return _unavailable("board_required")
        bridge = installed_bridge(board)
        # After the bridge: a host without the engine reports that first, since
        # no field would make the call succeed there. Field names come from
        # the closed list, never from the request.
        missing = [name for name in PREPARE_REQUIRED_FIELDS if name not in args]
        if missing:
            return _unavailable("invalid_prepare_input", fields=missing)
        schemas, hooks = host_capabilities()
        prepared = bridge.prepare(args, host=identity, schemas=schemas, hooks=hooks)
        return json.dumps(with_say(dict(prepared), board_say(prepared)), sort_keys=True)
    except BoardCoreUnavailable:
        # The module imported, but this host cannot import the engine behind
        # it; that is a missing component, not an invalid request.
        missing = getattr(module, "BOARD_CORE_IMPORT_FAILURE", "") or "unknown"
        return _unavailable("omh_agent_board_core_unavailable", detail=f"board_engine_unimportable:{missing}")
    except (ValueError, OSError):
        # Never echo exception strings, arguments, root paths or native output.
        return _unavailable("invalid_request_or_board_store")


def _unavailable(reason: str, *, detail: str = "", fields: list[str] | None = None) -> str:
    # `detail` names which import failed -- a module name, never an exception
    # string or a path -- so one reason no longer hides different faults.
    # `fields` names missing prepare fields, never a value.
    payload: dict[str, object] = {
        "schema_version": "agent_board_tool_result/v1", "state": "unavailable",
        "reason": reason, "native_action": None, "observed_receipts": [],
        "claim_boundary": "Unavailable preparation is not authorization or execution.",
    }
    if detail:
        payload["detail"] = detail
    if fields:
        payload["fields"] = fields
    return json.dumps(payload, sort_keys=True)
