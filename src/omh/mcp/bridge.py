from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

from ..version import __version__
from ..hud import build_hud_payload
from ..local_store import ensure_dir, ensure_file, read_jsonl_objects, utc_now
from ..paths import OmhPaths
from ..probe import probe_capabilities
from ..routing.recommend import recommend_skills
from ..runtime.artifacts import update_state

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_BRIDGE_SCHEMA_VERSION = "omh_mcp_bridge/v1"
MCP_TOOL_RESULT_SCHEMA_VERSION = "omh_mcp_tool_result/v1"
MCP_OBSERVATION_SCHEMA_VERSION = "omh_mcp_observation/v1"
MCP_HOST_SESSION_SCHEMA_VERSION = "omh_mcp_host_session/v1"
MCP_HOST_CONFIG_RECIPE_SCHEMA_VERSION = "omh_mcp_host_config_recipe/v1"
MCP_HOST_SESSION_EVENTS = ("host_load", "session_start", "tool_call", "session_end", "host_unload")
MCP_HOST_SESSION_STATUSES = ("observed", "not_observed", "blocked")
MCP_HOST_CONFIG_RECIPE_HOSTS = ("generic", "claude-code", "codex", "opencode", "cursor")
_MCP_HOST_CONFIG_RECIPE_ALIASES = {
    "generic": "generic",
    "mcp": "generic",
    "claude": "claude-code",
    "claude-code": "claude-code",
    "claude_code": "claude-code",
    "claude code": "claude-code",
    "codex": "codex",
    "openai-codex": "codex",
    "openai_codex": "codex",
    "opencode": "opencode",
    "open-code": "opencode",
    "open_code": "opencode",
    "open code": "opencode",
    "cursor": "cursor",
}

MCP_BRIDGE_CLAIM_BOUNDARY = (
    "The OMH MCP bridge exposes allowlisted local status, recommendation, and probe tools only. "
    "It is not arbitrary shell access, connector execution, coding dispatch, implementation, "
    "verification, review, CI, merge, or proof that a specific Hermes host loaded the bridge."
)

MCP_HOST_SESSION_CLAIM_BOUNDARY = (
    "An OMH MCP host session record is metadata supplied by a host or wrapper that observed bridge load/use. "
    "It is host-load/session evidence only, not arbitrary connector execution, coding dispatch, "
    "implementation, verification, review, CI, merge, or proof of any unrecorded tool call."
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
            "description": "Return local OMH capability probe data, optionally with the parity matrix and capability roadmap.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_parity": {"type": "boolean", "default": False},
                    "include_roadmap": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            "outputSchema": _tool_result_schema("omh_probe_result/v1"),
        },
    ]


def _mcp_server_args(paths: OmhPaths, *, include_absolute_homes: bool) -> list[str]:
    args = []
    if include_absolute_homes:
        args.extend(["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)])
    args.extend(["mcp", "serve"])
    return args


def _mcp_stdio_server(command: str, args: list[str], *, include_type: bool = False) -> dict[str, Any]:
    server: dict[str, Any] = {"command": command, "args": args}
    if include_type:
        server["type"] = "stdio"
    return server


def build_mcp_manifest(paths: OmhPaths, *, command: str = "omh", include_absolute_homes: bool = True) -> dict[str, Any]:
    args = _mcp_server_args(paths, include_absolute_homes=include_absolute_homes)
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
            "host_config_recipes_command": f"{command} mcp config-recipe --host <host>",
            "host_observation_command": (
                f"{command} mcp observe-host --host <host> --session <session-id> "
                "--event host_load --status observed --evidence-ref <host-log-or-session-ref>"
            ),
            "normal_hermes_surface": "Use installed OMH skills in Hermes chat first; use this MCP bridge only when the host supports MCP tools.",
        },
        "claim_boundary": MCP_BRIDGE_CLAIM_BOUNDARY,
    }


def build_mcp_host_config_recipe(
    paths: OmhPaths,
    *,
    host: str = "generic",
    command: str = "omh",
    include_absolute_homes: bool = True,
) -> dict[str, Any]:
    host = _normalize_recipe_host(host)
    args = _mcp_server_args(paths, include_absolute_homes=include_absolute_homes)
    generic_server = _mcp_stdio_server(command, args)
    typed_stdio_server = _mcp_stdio_server(command, args, include_type=True)
    if host == "generic":
        snippet: dict[str, Any] | str = {"mcpServers": {"omh": generic_server}}
        snippet_text = _pretty_json(snippet)
        config_format = "json"
        target_paths = ["mcp.json", ".mcp.json"]
        target_notes = ["Some MCP hosts use a host-specific MCP config file or settings panel."]
        apply_steps = [
            "Open the MCP-capable host configuration file.",
            "Merge the mcpServers.omh entry into the existing config.",
            "Restart or reload the host, then record observed load with omh mcp observe-host.",
        ]
        source_urls = ["https://modelcontextprotocol.io"]
    elif host == "claude-code":
        snippet = {"mcpServers": {"omh": typed_stdio_server}}
        snippet_text = _pretty_json(snippet)
        config_format = "json"
        target_paths = [".mcp.json", "~/.claude.json"]
        target_notes = ["Claude Code can also add the same stdio command through `claude mcp add`."]
        apply_steps = [
            "For project scope, merge this into .mcp.json at the project root.",
            "Alternatively use Claude Code's MCP CLI to add the same stdio command.",
            "Open Claude Code and approve the project MCP server if prompted, then record observed load with omh mcp observe-host.",
        ]
        source_urls = ["https://code.claude.com/docs/en/mcp", "https://docs.anthropic.com/en/docs/claude-code/settings"]
    elif host == "codex":
        snippet = _codex_mcp_toml(command, args)
        snippet_text = snippet
        config_format = "toml"
        target_paths = ["~/.codex/config.toml", ".codex/config.toml"]
        target_notes = ["Use the user config for global availability or project config for one repository."]
        apply_steps = [
            "Merge the [mcp_servers.omh] table into the target Codex config.toml.",
            "Restart or reload Codex so it can start the stdio MCP server.",
            "Record observed load or tool use with omh mcp observe-host after the host actually uses the bridge.",
        ]
        source_urls = [
            "https://developers.openai.com/codex/config-basic",
            "https://developers.openai.com/codex/config-reference",
        ]
    elif host == "opencode":
        snippet = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "omh": {
                    "type": "local",
                    "command": [command, *args],
                    "enabled": True,
                }
            },
        }
        snippet_text = _pretty_json(snippet)
        config_format = "json"
        target_paths = ["opencode.json", "opencode.jsonc"]
        target_notes = ["OpenCode supports local MCP servers under the mcp config object."]
        apply_steps = [
            "Merge the mcp.omh entry into the OpenCode config.",
            "Restart or reload OpenCode so it can start the local MCP server.",
            "Record observed load or tool use with omh mcp observe-host after OpenCode actually connects.",
        ]
        source_urls = ["https://opencode.ai/docs/mcp-servers/", "https://opencode.ai/docs/config/"]
    else:
        snippet = {"mcpServers": {"omh": typed_stdio_server}}
        snippet_text = _pretty_json(snippet)
        config_format = "json"
        target_paths = [".cursor/mcp.json", "~/.cursor/mcp.json"]
        target_notes = ["Cursor MCP settings can create or open the active MCP JSON config for the current version."]
        apply_steps = [
            "Open Cursor MCP settings or the project/user MCP JSON file supported by the current Cursor version.",
            "Merge the mcpServers.omh entry into the existing config.",
            "Reload Cursor and record observed load or tool use with omh mcp observe-host after it actually connects.",
        ]
        source_urls = ["https://cursor.com/docs/mcp"]
    return {
        "schema_version": MCP_HOST_CONFIG_RECIPE_SCHEMA_VERSION,
        "host": host,
        "known_hosts": list(MCP_HOST_CONFIG_RECIPE_HOSTS),
        "config_format": config_format,
        "target_paths": target_paths,
        "target_notes": target_notes,
        "server": {
            "name": "omh",
            "transport": "stdio",
            "command": command,
            "args": args,
            "tools": [tool["name"] for tool in mcp_tool_definitions()],
        },
        "snippet": snippet,
        "snippet_text": snippet_text,
        "apply_steps": apply_steps,
        "verify": {
            "local_command": f"{command} mcp manifest",
            "host_observation_command": (
                f"{command} mcp observe-host --host {host} --session <session-id> "
                "--event host_load --status observed --evidence-ref <host-log-or-session-ref>"
            ),
            "boundary": "A pasted host config is not evidence that the host loaded OMH; record a host observation only after the host actually loads or uses the bridge.",
        },
        "source_urls": source_urls,
        "claim_boundary": MCP_BRIDGE_CLAIM_BOUNDARY,
    }


def _normalize_recipe_host(host: str) -> str:
    normalized = " ".join(str(host or "generic").strip().lower().replace("_", " ").split())
    normalized = normalized.replace(" ", "-") if normalized in {"claude code", "openai codex", "open code"} else normalized
    normalized = _MCP_HOST_CONFIG_RECIPE_ALIASES.get(normalized, normalized)
    if normalized not in MCP_HOST_CONFIG_RECIPE_HOSTS:
        raise ValueError(f"mcp config recipe host must be one of: {', '.join(MCP_HOST_CONFIG_RECIPE_HOSTS)}")
    return normalized


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _codex_mcp_toml(command: str, args: list[str]) -> str:
    return "\n".join(
        [
            "[mcp_servers.omh]",
            f"command = {_toml_string(command)}",
            f"args = {_toml_array(args)}",
            "enabled = true",
            'enabled_tools = ["omh_status", "omh_recommend", "omh_probe"]',
        ]
    ) + "\n"


def record_mcp_host_session(
    paths: OmhPaths,
    *,
    host: str,
    session_id: str,
    event: str,
    status: str,
    evidence_refs: list[str] | None = None,
    message: str = "",
    source: str = "wrapper",
    tool: str = "",
) -> dict[str, Any]:
    host = host.strip()
    session_id = session_id.strip()
    event = event.strip()
    status = status.strip()
    source = source.strip() or "wrapper"
    tool = tool.strip()
    evidence_refs = [item.strip() for item in (evidence_refs or []) if item and item.strip()]
    if not host:
        raise ValueError("mcp host observation requires --host")
    if not session_id:
        raise ValueError("mcp host observation requires --session")
    if event not in MCP_HOST_SESSION_EVENTS:
        raise ValueError(f"mcp host observation event must be one of: {', '.join(MCP_HOST_SESSION_EVENTS)}")
    if status not in MCP_HOST_SESSION_STATUSES:
        raise ValueError(f"mcp host observation status must be one of: {', '.join(MCP_HOST_SESSION_STATUSES)}")
    if status == "observed" and not evidence_refs:
        raise ValueError("observed MCP host sessions require at least one --evidence-ref")
    if event == "tool_call" and not tool:
        raise ValueError("mcp host tool_call observation requires --tool")

    recorded_at = utc_now()
    record: dict[str, Any] = {
        "schema_version": MCP_HOST_SESSION_SCHEMA_VERSION,
        "host": host,
        "session_id": session_id,
        "event": event,
        "status": status,
        "observed": status == "observed",
        "source": source,
        "tool": tool,
        "evidence_refs": evidence_refs,
        "message": message.strip(),
        "recorded_at": recorded_at,
        "claim_boundary": MCP_HOST_SESSION_CLAIM_BOUNDARY,
    }
    if status == "observed":
        record["observed_at"] = recorded_at
    _append_mcp_host_session(paths, record)
    patch: dict[str, Any] = {"last_mcp_host_session": record}
    if record["observed"]:
        patch["last_mcp_host_observed"] = record
    update_state(paths, patch)
    return record


def read_mcp_host_sessions(paths: OmhPaths, *, limit: int | None = 20) -> tuple[list[dict[str, Any]], list[str]]:
    records, errors = read_jsonl_objects(paths.runtime_mcp_host_sessions_path)
    records = list(reversed(records))
    if limit is not None:
        records = records[:limit]
    return records, errors


def latest_observed_mcp_host_session(paths: OmhPaths) -> tuple[dict[str, Any] | None, list[str]]:
    records, errors = read_jsonl_objects(paths.runtime_mcp_host_sessions_path)
    for record in reversed(records):
        if record.get("schema_version") == MCP_HOST_SESSION_SCHEMA_VERSION and record.get("observed"):
            return record, errors
    return None, errors


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


def _append_mcp_host_session(paths: OmhPaths, record: dict[str, Any]) -> None:
    ensure_dir(paths.runtime_dir, private=True)
    ensure_file(paths.runtime_mcp_host_sessions_path, private=True)
    with paths.runtime_mcp_host_sessions_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


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
    raw_arguments = params.get("arguments")
    arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
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
        include_roadmap = bool(arguments.get("include_roadmap", False))
        probe = probe_capabilities(paths, include_parity=include_parity, include_roadmap=include_roadmap)
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
