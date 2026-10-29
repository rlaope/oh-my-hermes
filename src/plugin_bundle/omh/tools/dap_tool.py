"""`debug_python`: opt-in Python debugger tool over debugpy's Debug Adapter Protocol.

Registered under the dedicated toolset `omh-dap` and hidden behind a `check_fn` (env
`OMH_DAP_TOOLS` or the profile setting `plugins.entries.omh.settings.dap_tools`), so
normal sessions pay no schema cost. The handler returns one JSON string and never
raises. Session and action rules live in `omh.dap_session`; the process and the wire
live in `omh.dap_client`.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .. import dap_client
from .. import runtime_paths as _runtime_paths
from ..dap_client import DapError
from ..dap_session import SessionError, SessionManager

DAP_TOOLSET = "omh-dap"

OMH_DAP_DEBUG_PYTHON_SCHEMA = {
    "name": "debug_python",
    "description": (
        "Debug a Python run (default: pytest) with debugpy: launch with breakpoints, then at each stop "
        "inspect frames/locals or evaluate expressions, step or continue, terminate. One session per task; "
        "evaluate runs code inside the workspace's own program; at most 15 evaluations per stop."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": ["launch", "set_breakpoints", "continue", "step_over", "step_in", "step_out",
                         "inspect", "evaluate", "terminate"],
            },
            "python": {"type": "string", "description": "launch: interpreter with debugpy installed"},
            "module": {"type": "string", "description": "launch: module to run (pytest when no program)"},
            "program": {"type": "string", "description": "launch: script path instead of module"},
            "args": {"type": "array", "items": {"type": "string"}, "description": "launch: program arguments"},
            "breakpoints": {
                "type": "array",
                "description": "launch: initial breakpoints",
                "items": {
                    "type": "object", "required": ["path", "line"],
                    "properties": {"path": {"type": "string"}, "line": {"type": "integer"},
                                   "condition": {"type": "string"}},
                },
            },
            "path": {"type": "string", "description": "set_breakpoints: file whose breakpoints are replaced"},
            "lines": {"type": "array", "items": {"type": "integer"}, "description": "set_breakpoints: [] clears"},
            "condition": {"type": "string", "description": "set_breakpoints: stop only when this is true"},
            "frame": {"type": "integer", "minimum": 0, "description": "inspect/evaluate: stack index, innermost first"},
            "expression": {"type": "string", "description": "evaluate: Python expression"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 180,
                        "description": "launch/continue/step: seconds to wait for a stop"},
        },
    },
}

_ON = ("1", "true", "on", "yes")
_ACTIONS = frozenset(OMH_DAP_DEBUG_PYTHON_SCHEMA["parameters"]["properties"]["action"]["enum"])


def _dap_tools_enabled() -> bool:
    """`check_fn`: True when env `OMH_DAP_TOOLS` or the active profile's
    `plugins.entries.omh.settings.dap_tools` setting is on.

    The gateway builds tool definitions in its own process, so a client's env never
    reaches this check; the profile setting is read from the profile's `config.yaml`
    text. Any read failure is off.
    """
    if os.environ.get("OMH_DAP_TOOLS", "").strip().lower() in _ON:
        return True
    try:
        text = (_runtime_paths.default_hermes_home() / "config.yaml").read_text(encoding="utf-8")
        value = _runtime_paths.plugin_setting_text(text, "dap_tools")
    except Exception:
        return False
    return value is not None and value.strip().lower() in _ON


def _workspace_root(task_id: object) -> str | None:
    """The session's workspace root as Hermes' own file tools resolve it (``TERMINAL_CWD`` fallback)."""
    try:
        from tools.file_tools_paths import _resolve_base_dir

        return str(_resolve_base_dir(str(task_id or "default"), container_paths=False))
    except Exception:
        return os.environ.get("TERMINAL_CWD")


def _fail(code: str, hint: str, **extra: Any) -> str:
    return json.dumps({"ok": False, "error": code, "hint": hint, **extra}, ensure_ascii=False)


def _new_client(argv: list[str], cwd: str, env: dict[str, str]) -> dap_client.DapClient:
    return dap_client.DapClient(argv, cwd, env)


SESSIONS = SessionManager(_new_client)


def debug_python_handler(args: dict[str, Any], **kwargs: object) -> str:
    try:
        action = args.get("action")
        if action not in _ACTIONS:
            return _fail("invalid_argument", f"action must be one of {sorted(_ACTIONS)}")
        root = _workspace_root(kwargs.get("task_id"))
        root = os.path.realpath(root if root else os.getcwd())
        key = str(kwargs.get("task_id") or "default")
        return json.dumps(SESSIONS.run(key, str(action), args, root), ensure_ascii=False)
    except SessionError as exc:
        return _fail(exc.code, exc.hint, **exc.extra)
    except DapError as exc:
        return _fail(exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - never raise to the host
        return _fail("unexpected_error", type(exc).__name__)


__all__ = [
    "DAP_TOOLSET",
    "OMH_DAP_DEBUG_PYTHON_SCHEMA",
    "SESSIONS",
    "_dap_tools_enabled",
    "_workspace_root",
    "debug_python_handler",
]
