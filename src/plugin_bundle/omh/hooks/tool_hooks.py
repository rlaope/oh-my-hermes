from __future__ import annotations

import json

from ..omh_roles import extract_role_marker, role_names


def pre_tool_call(**kwargs) -> dict[str, str] | None:
    """Warn when a delegate_task goal uses an unknown OMH role marker."""
    if str(kwargs.get("tool_name", "") or "") != "delegate_task":
        return None
    tool_input = kwargs.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            parsed = json.loads(tool_input)
        except json.JSONDecodeError:
            return None
        tool_input = parsed if isinstance(parsed, dict) else {}
    if not isinstance(tool_input, dict):
        return None
    marker = extract_role_marker(str(tool_input.get("goal", "") or ""))
    if not marker:
        return None
    available = role_names()
    if marker in available:
        return None
    return {
        "context": (
            f"[OMH Role Warning] Unknown role '{marker}' in delegate_task goal. "
            f"Available roles: {', '.join(available) or '(none)'}. "
            "No OMH role context will be injected for that subagent."
        )
    }
