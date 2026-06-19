from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

from . import __version__
from .hud import build_hud_payload
from .paths import OmhPaths
from .probe import probe_capabilities
from .routing.recommend import recommend_skills
from .runtime.artifacts import update_state

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_BRIDGE_SCHEMA_VERSION = "omh_mcp_bridge/v1"
MCP_TOOL_RESULT_SCHEMA_VERSION = "omh_mcp_tool_result/v1"
MCP_OBSERVATION_SCHEMA_VERSION = "omh_mcp_observation/v1"

MCP_BRIDGE_CLAIM_BOUNDARY = (
    "The OMH MCP bridge exposes allowlisted local status, recommendation, and probe tools only. "
    "It is not arbitrary shell access, connector execution, coding dispatch, implementation, "
    "verification, review, CI, merge, or proof that a specific Hermes host loaded the bridge."
)


def mcp_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "omh_status",
            "title": "OMH Status",
            "description": "Return the compact OMH HUD/status payload for Hermes-facing status narration.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "preset": {
                        "type": "string",
                        "enum": ["minimal", "focused", "full"],
                        "default": "focused",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 3,
                    },
                },
                "additionalProperties": False,
            },
            "outputSchema": _tool_result_schema("omh_status_result/v1"),
        },
        {
            "name": "omh_recommend",
            "title": "OMH Workflow Recommendation",
            "description": "Recommend OMH workflows for a natural-language operator request without storing the raw request.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "minLength": 1},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            "outputSchema": _tool_result_schema("omh_recommend_result/v1"),
        },
        {
            "name": "omh_probe",
            "title": "OMH Capability Probe",
            "description": "Return local OMH capability probe data, optionally with the parity matrix.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_parity": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            "outputSchema": _tool_result_schema("omh_probe_result/v1"),
        },
    ]


def build_mcp_manifest(paths: OmhPaths, *, command: str = "omh", include_absolute_homes: bool = True) -> dict[str, Any]:
    args = []
    if include_absolute_homes:
        args.extend(["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)])
    args.extend(["mcp", "serve"])
    return {
        "schema_version": MCP_BRIDGE_SCHEMA_VERSION,
        "name": "omh",
        "version": __version__,
        "transport": "stdio",
        "server": {
            "command": command,
            "args": args,
            "env": {},
        },
        "host_config_snippets": {
            "generic_mcp_servers": {
                "mcpServers": {
                    "omh": {
                        "command": command,
                        "args": args,
                    }
                }
            }
        },
        "tools": mcp_tool_definitions(),
        "setup": {
            "operator_command": f"{command} mcp manifest",
            "server_command": " ".join([command, *args]),
            "normal_hermes_surface": "Use installed OMH skills in Hermes chat first; use this MCP bridge only when the host supports MCP tools.",
        },
        "claim_boundary": MCP_BRIDGE_CLAIM_BOUNDARY,
    }


def run_stdio_mcp_server(paths: OmhPaths, *, stdin: TextIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle_mcp_message(paths, message)
        except Exception as exc:  # pragma: no cover - defensive transport boundary
            print(f"omh mcp bridge error: {exc}", file=error_stream)
            response = _error_response(None, -32603, "Internal error")
        if response is None:
            continue
        output_stream.write(json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n")
        output_stream.flush()
    return 0


def handle_mcp_message(paths: OmhPaths, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return _error_response(None, -32600, "Invalid Request")
    if message.get("jsonrpc") != "2.0":
        return _error_response(message.get("id"), -32600, "Invalid Request")
    method = message.get("method")
    request_id = message.get("id")
    if not method:
        return None
    if request_id is None and str(method).startswith("notifications/"):
        return None
    if method == "initialize":
        return _result_response(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "omh", "version": __version__},
                "instructions": (
                    "Use OMH tools for local status, workflow recommendation, and capability probes only. "
                    "Do not treat bridge output as execution, review, CI, or merge evidence."
                ),
            },
        )
    if method == "ping":
        return _result_response(request_id, {})
    if method == "tools/list":
        return _result_response(request_id, {"tools": mcp_tool_definitions()})
    if method == "tools/call":
        return _handle_tool_call(paths, request_id, _params(message))
    if method == "resources/list":
        return _result_response(request_id, {"resources": []})
    if method == "prompts/list":
        return _result_response(request_id, {"prompts": []})
    return _error_response(request_id, -32601, f"Method not found: {method}")


def _handle_tool_call(paths: OmhPaths, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name", ""))
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    try:
        structured = _call_tool(paths, name, arguments)
    except ValueError as exc:
        return _tool_response(request_id, _error_tool_result(name, str(exc)), is_error=True)
    _record_tool_call(paths, name)
    return _tool_response(request_id, structured, is_error=False)


def _call_tool(paths: OmhPaths, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "omh_status":
        preset = str(arguments.get("preset") or "focused")
        if preset not in {"minimal", "focused", "full"}:
            raise ValueError("omh_status.preset must be minimal, focused, or full")
        limit = _bounded_int(arguments.get("limit"), default=3, minimum=1, maximum=20)
        hud = build_hud_payload(paths, preset=preset, limit=limit)
        return _tool_result(
            "omh_status_result/v1",
            "omh_status",
            {
                "line": hud.get("display", {}).get("line", ""),
                "hud": hud,
            },
        )
    if name == "omh_recommend":
        message = str(arguments.get("message") or "").strip()
        if not message:
            raise ValueError("omh_recommend.message is required")
        limit = _bounded_int(arguments.get("limit"), default=5, minimum=1, maximum=10)
        recommendations = recommend_skills(message, limit=limit)
        return _tool_result(
            "omh_recommend_result/v1",
            "omh_recommend",
            {
                "message_summary": f"{len(message)} characters; raw prompt not stored by the bridge",
                "recommendations": recommendations,
            },
        )
    if name == "omh_probe":
        include_parity = bool(arguments.get("include_parity", False))
        probe = probe_capabilities(paths, include_parity=include_parity)
        return _tool_result("omh_probe_result/v1", "omh_probe", {"probe": probe})
    raise ValueError(f"Unknown tool: {name}")


def _tool_result(result_schema_version: str, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": MCP_TOOL_RESULT_SCHEMA_VERSION,
        "result_schema_version": result_schema_version,
        "tool": tool,
        "status": "observed_tool_call",
        "payload": payload,
        "claim_boundary": MCP_BRIDGE_CLAIM_BOUNDARY,
    }


def _error_tool_result(tool: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": MCP_TOOL_RESULT_SCHEMA_VERSION,
        "result_schema_version": "omh_tool_error/v1",
        "tool": tool or "unknown",
        "status": "tool_error",
        "error": message,
        "payload": {},
        "claim_boundary": MCP_BRIDGE_CLAIM_BOUNDARY,
    }


def _tool_response(request_id: Any, structured: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    text = json.dumps(structured, separators=(",", ":"), sort_keys=True)
    result = {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": bool(is_error),
    }
    return _result_response(request_id, result)


def _record_tool_call(paths: OmhPaths, tool: str) -> None:
    update_state(
        paths,
        {
            "last_mcp_bridge": {
                "schema_version": MCP_OBSERVATION_SCHEMA_VERSION,
                "observed": True,
                "event": "tool_call",
                "tool": tool,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "claim_boundary": (
                    "A local MCP bridge tool call was observed by OMH. This is not proof that a specific Hermes host "
                    "loaded the bridge unless the host records its own load/session evidence."
                ),
            }
        },
    )


def _params(message: dict[str, Any]) -> dict[str, Any]:
    params = message.get("params")
    return params if isinstance(params, dict) else {}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result_schema(result_schema_version: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schema_version": {"const": MCP_TOOL_RESULT_SCHEMA_VERSION},
            "result_schema_version": {"const": result_schema_version},
            "tool": {"type": "string"},
            "status": {"type": "string"},
            "payload": {"type": "object"},
            "claim_boundary": {"type": "string"},
        },
        "required": ["schema_version", "result_schema_version", "tool", "status", "payload", "claim_boundary"],
    }
