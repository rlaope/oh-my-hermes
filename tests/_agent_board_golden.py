"""Produce the `omh_agent_board` outputs the golden fixture pins.

The fixture (`fixtures/agent_board_golden.json`) was captured at origin/main
1239b36bd, which has no `omh_team`, by running this producer (re-captured
there after main changed the tool's own schema text, again when #2277
added the prepare fields to it, and when its description gained a short
first sentence for Hermes' tool_search listing). The team lane
is a separate tool precisely so this tool stays what it was; the test that
reads the fixture compares STRINGS, not parsed dicts, because a dict compare
cannot see key order and this pin is about bytes a host reads.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

_MINIMAL_ARGUMENTS: dict[str, dict[str, object]] = {
    "create": {"title": "qa-task", "assignee": "qa-profile"},
    "link": {"parent_id": "T1", "child_id": "T2"},
    "comment": {"body": "note"},
    "heartbeat": {},
    "request_review": {"summary": "ready"},
    "request_changes": {"reason": "fix"},
    "block": {"reason": "stuck"},
    "unblock": {},
    "complete": {"summary": "done"},
    "show": {},
    "list": {},
    "attachments": {},
}


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _prepare(bridge: object, payload: dict[str, object], **kwargs: object) -> str:
    """The prepared result, or the refusal the bridge raises, as one string."""
    try:
        return _dump(bridge.prepare(payload, **kwargs))  # type: ignore[attr-defined]
    except ValueError as error:
        return f"raises:{type(error).__name__}:{error}"


def agent_board_golden_outputs() -> dict[str, str]:
    """Every pinned output, keyed by a stable case name."""
    from five_issue_cases.kanban import request, supplied_schemas
    from omh.plugin_bundle.omh import agent_board_bridge
    from omh.plugin_bundle.omh.tools import agent_board_tool
    from omh.workflows.agent_board import HostIdentity, LANE_ROLES, _OPERATIONS

    hooks = frozenset({"pre_tool_call", "post_tool_call"})
    host = HostIdentity("session", "host-task", "prepare")
    outputs: dict[str, str] = {"schema": _dump(agent_board_tool.OMH_AGENT_BOARD_SCHEMA)}
    with TemporaryDirectory() as tmp:
        bridge = agent_board_bridge.AgentBoardBridge(Path(tmp), root_identity="fixture-root")
        for operation in sorted(_OPERATIONS):
            extra = {} if operation in ("create", "link", "list") else {"task_id": "T1"}
            outputs[f"prepare:{operation}"] = _prepare(
                bridge,
                request(operation, request_id=f"golden-{operation}", arguments=dict(_MINIMAL_ARGUMENTS[operation]),
                        **extra),
                host=host, schemas=supplied_schemas(), hooks=hooks,
            )
        for role in sorted(LANE_ROLES):
            with_parents = {"title": f"{role}-task", "assignee": "qa-profile", "lane_role": role, "parents": ["T1"]}
            outputs[f"lane_role:{role}"] = _prepare(
                bridge, request("create", request_id=f"golden-role-{role}", arguments=with_parents),
                host=host, schemas=supplied_schemas(), hooks=hooks)
            without_parents = {"title": f"{role}-task", "assignee": "qa-profile", "lane_role": role}
            outputs[f"lane_role_without_parents:{role}"] = _prepare(
                bridge, request("create", request_id=f"golden-role-{role}-bare", arguments=without_parents),
                host=host, schemas=supplied_schemas(), hooks=hooks)
        outputs["status:prepared"] = _dump(bridge.status("qa-board", "golden-create"))
        outputs["status:missing"] = _dump(bridge.status("qa-board", "golden-never-prepared"))
    outputs["handler:invalid_status_input"] = agent_board_tool.omh_agent_board_handler(
        {"action": "status", "request_id": "r", "board": "extra"})
    outputs["handler:board_required"] = agent_board_tool.omh_agent_board_handler(
        {"action": "prepare", "request_id": "r"})
    for reason in ("omh_agent_board_core_unavailable", "invalid_request_or_board_store"):
        outputs[f"unavailable:{reason}"] = agent_board_tool._unavailable(reason)
    return outputs


if __name__ == "__main__":
    print(json.dumps(agent_board_golden_outputs(), indent=2, sort_keys=True))
