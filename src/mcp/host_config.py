from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_text
from ..paths import expand_path

MCP_HOST_CONFIG_INSTALL_SCHEMA_VERSION = "omh_mcp_host_config_install/v1"
MCP_HOST_CONFIG_RECIPE_HOSTS = ("generic", "claude-code", "codex", "opencode", "cursor")
MCP_HOST_CONFIG_INSTALL_HOSTS = ("claude-code", "codex", "opencode", "cursor")
MCP_HOST_CONFIG_RECIPE_CLAIM_BOUNDARY = (
    "OMH MCP host config recipes are setup guidance only. They are not arbitrary shell access, "
    "connector execution, coding dispatch, implementation, verification, review, CI, merge, "
    "or proof that a specific Hermes host loaded the bridge."
)


def install_mcp_host_config(
    paths,
    *,
    host: str,
    command: str = "omh",
    config_path: str | Path | None = None,
    scope: str = "user",
    dry_run: bool = False,
) -> dict[str, object]:
    from .bridge import build_mcp_host_config_recipe

    recipe = build_mcp_host_config_recipe(paths, host=host, command=command)
    normalized_host = str(recipe["host"])
    if normalized_host == "generic":
        return _skipped_result(
            host=normalized_host,
            reason="generic host recipes are copy-paste only",
            command=command,
            config_path=config_path,
            scope=scope,
            dry_run=dry_run,
        )
    if normalized_host not in MCP_HOST_CONFIG_INSTALL_HOSTS:
        return _skipped_result(
            host=normalized_host,
            reason="host is not supported by automatic config install",
            command=command,
            config_path=config_path,
            scope=scope,
            dry_run=dry_run,
        )

    target_path = _target_config_path(normalized_host, config_path=config_path, scope=scope)
    args = list(recipe["server"]["args"]) if isinstance(recipe.get("server"), dict) else ["mcp", "serve"]
    before = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    if normalized_host == "codex":
        after = _ensure_codex_toml_server(before, command=command, args=args)
    elif normalized_host == "opencode":
        after = _ensure_json_server(
            before,
            normalized_host,
            {"type": "local", "command": [command, *args], "enabled": True},
        )
    else:
        after = _ensure_json_server(
            before,
            normalized_host,
            {"command": command, "args": args, "type": "stdio"},
        )

    changed = before != after
    if dry_run:
        status = "dry_run_would_write" if changed else "dry_run_unchanged"
    else:
        status = "updated" if changed else "unchanged"
    if changed and not dry_run:
        atomic_write_text(target_path, after)
    return {
        "schema_version": MCP_HOST_CONFIG_INSTALL_SCHEMA_VERSION,
        "host": normalized_host,
        "status": status,
        "changed": bool(changed),
        "written": bool(changed and not dry_run),
        "dry_run": bool(dry_run),
        "scope": _normalized_scope(scope),
        "path": str(target_path),
        "command": command,
        "server_args": args,
        "tools": list(recipe["server"]["tools"]) if isinstance(recipe.get("server"), dict) else [],
        "host_config_observed": bool(target_path.exists() if not dry_run else False),
        "host_runtime_observed": False,
        "host_observation_command": (
            f"{command} mcp observe-host --host {normalized_host} --session <session-id> "
            "--event host_load --status observed --evidence-ref <host-log-or-session-ref>"
        ),
        "claim_boundary": (
            "OMH wrote or planned a local MCP host config entry only. This does not prove the host loaded "
            "OMH, started the stdio server, called a tool, executed a connector, dispatched coding work, "
            "verified output, reviewed a PR, passed CI, or merged."
        ),
    }


def mcp_host_config_entry_present(host: str, path: str | Path) -> bool:
    target_path = expand_path(path)
    if not target_path.exists() or not target_path.is_file():
        return False
    try:
        config_text = target_path.read_text(encoding="utf-8")
        normalized_host = str(host or "").strip().lower()
        if normalized_host == "codex":
            return _codex_server_present(config_text)
        if normalized_host == "opencode":
            data = _read_json_config(config_text)
            mcp = data.get("mcp")
            server = mcp.get("omh") if isinstance(mcp, dict) else None
            return _json_server_present(server, command_as_list=True)
        if normalized_host in {"claude-code", "cursor"}:
            data = _read_json_config(config_text)
            mcp_servers = data.get("mcpServers")
            server = mcp_servers.get("omh") if isinstance(mcp_servers, dict) else None
            return _json_server_present(server, command_as_list=False)
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return False
    return False


def _skipped_result(
    *,
    host: str,
    reason: str,
    command: str,
    config_path: str | Path | None,
    scope: str,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "schema_version": MCP_HOST_CONFIG_INSTALL_SCHEMA_VERSION,
        "host": host,
        "status": "skipped",
        "changed": False,
        "written": False,
        "dry_run": bool(dry_run),
        "scope": _normalized_scope(scope),
        "path": str(expand_path(config_path)) if config_path else "",
        "command": command,
        "server_args": ["mcp", "serve"],
        "tools": ["omh_status", "omh_recommend", "omh_probe"],
        "host_config_observed": False,
        "host_runtime_observed": False,
        "reason": reason,
        "claim_boundary": MCP_HOST_CONFIG_RECIPE_CLAIM_BOUNDARY,
    }


def _target_config_path(host: str, *, config_path: str | Path | None, scope: str) -> Path:
    if config_path:
        return expand_path(config_path)
    normalized_scope = _normalized_scope(scope)
    cwd = Path.cwd()
    home = Path.home()
    if host == "codex":
        if normalized_scope == "project":
            return (cwd / ".codex" / "config.toml").resolve()
        return expand_path(home / ".codex" / "config.toml")
    if host == "claude-code":
        if normalized_scope == "project":
            return (cwd / ".mcp.json").resolve()
        return expand_path(home / ".claude.json")
    if host == "opencode":
        if normalized_scope == "project":
            return (cwd / "opencode.json").resolve()
        return expand_path(home / ".config" / "opencode" / "opencode.json")
    if host == "cursor":
        if normalized_scope == "project":
            return (cwd / ".cursor" / "mcp.json").resolve()
        return expand_path(home / ".cursor" / "mcp.json")
    raise ValueError(f"mcp host config install host must be one of: {', '.join(MCP_HOST_CONFIG_RECIPE_HOSTS)}")


def _normalized_scope(scope: str) -> str:
    normalized = str(scope or "user").strip().lower()
    return "project" if normalized == "project" else "user"


def _ensure_json_server(config_text: str, host: str, server: dict[str, Any]) -> str:
    data = _read_json_config(config_text)
    if host == "opencode":
        mcp = data.get("mcp")
        if not isinstance(mcp, dict):
            mcp = {}
        mcp["omh"] = server
        data["mcp"] = mcp
    else:
        mcp_servers = data.get("mcpServers")
        if not isinstance(mcp_servers, dict):
            mcp_servers = {}
        mcp_servers["omh"] = server
        data["mcpServers"] = mcp_servers
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _read_json_config(config_text: str) -> dict[str, Any]:
    stripped = config_text.strip()
    if not stripped:
        return {}
    loaded = json.loads(stripped)
    if not isinstance(loaded, dict):
        raise ValueError("MCP host config must be a JSON object")
    return loaded


def _ensure_codex_toml_server(config_text: str, *, command: str, args: list[str]) -> str:
    block = "\n".join(
        [
            "[mcp_servers.omh]",
            f"command = {_toml_string(command)}",
            f"args = {_toml_array(args)}",
            "enabled = true",
            'enabled_tools = ["omh_status", "omh_recommend", "omh_probe"]',
        ]
    )
    lines = config_text.splitlines()
    output: list[str] = []
    index = 0
    removed = False
    while index < len(lines):
        if _codex_omh_table_header(lines[index]):
            removed = True
            index += 1
            while index < len(lines) and not _toml_table_header(lines[index]):
                index += 1
            continue
        output.append(lines[index])
        index += 1
    prefix = "\n".join(output).rstrip()
    separator = "\n\n" if prefix else ""
    suffix = "\n" if removed or config_text.endswith("\n") or prefix else ""
    return f"{prefix}{separator}{block}{suffix}".rstrip() + "\n"


def _codex_server_present(config_text: str) -> bool:
    data = tomllib.loads(config_text or "")
    mcp_servers = data.get("mcp_servers")
    server = mcp_servers.get("omh") if isinstance(mcp_servers, dict) else None
    return _json_server_present(server, command_as_list=False)


def _json_server_present(server: object, *, command_as_list: bool) -> bool:
    if not isinstance(server, dict):
        return False
    if command_as_list:
        command = server.get("command")
        return isinstance(command, list) and len(command) >= 3 and command[-2:] == ["mcp", "serve"]
    command = server.get("command")
    args = server.get("args")
    return isinstance(command, str) and bool(command.strip()) and isinstance(args, list) and args[-2:] == ["mcp", "serve"]


def _toml_table_header(line: str) -> bool:
    return _toml_header_name(line) is not None


def _codex_omh_table_header(line: str) -> bool:
    name = _toml_header_name(line)
    return bool(name == "mcp_servers.omh" or (name and name.startswith("mcp_servers.omh.")))


def _toml_header_name(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[["):
        match = re.match(r"^\s*\[\[([^\]]+)\]\]", line)
        return match.group(1).strip() if match else None
    match = re.match(r"^\s*\[([^\]]+)\]", line)
    return match.group(1).strip() if match else None


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"
