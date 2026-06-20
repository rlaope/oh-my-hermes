from __future__ import annotations

import json

from ..awareness import generic_tool_checkpoint_routes
from ..host_observation import observe_plugin_hook_call
from ..omh_roles import extract_role_marker, resolve_role_name, role_aliases, role_names


def pre_tool_call(**kwargs) -> dict[str, str] | None:
    """Inject bounded OMH context before tool calls without exposing tool input."""
    observe_plugin_hook_call("pre_tool_call", kwargs)
    context_parts: list[str] = []
    role_warning = _delegate_role_warning(kwargs)
    if role_warning:
        context_parts.append(role_warning)

    checkpoint = _generic_tool_checkpoint_context(kwargs)
    if checkpoint:
        context_parts.append(checkpoint)

    if not context_parts:
        return None
    return {"context": "\n\n".join(context_parts)}


def _delegate_role_warning(kwargs: dict) -> str:
    if str(kwargs.get("tool_name", "") or "") != "delegate_task":
        return ""
    tool_input = kwargs.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            parsed = json.loads(tool_input)
        except json.JSONDecodeError:
            return ""
        tool_input = parsed if isinstance(parsed, dict) else {}
    if not isinstance(tool_input, dict):
        return ""
    marker = extract_role_marker(str(tool_input.get("goal", "") or ""))
    if not marker:
        return ""
    available = role_names()
    aliases = role_aliases()
    if marker in available or resolve_role_name(marker) in available:
        return ""
    return (
        f"[OMH Role Warning] Unknown role '{marker}' in delegate_task goal. "
        f"Available roles: {', '.join(available) or '(none)'}. "
        f"Legacy aliases: {', '.join(sorted(aliases)) or '(none)'}. "
        "No OMH role context will be injected for that subagent."
    )


def _generic_tool_checkpoint_context(kwargs: dict) -> str:
    if kwargs.get("include_omh_tool_checkpoint", True) is False:
        return ""
    route = _generic_tool_route(kwargs)
    if not route:
        return ""
    tool_name = str(kwargs.get("tool_name", "") or "").strip() or "unknown"
    preferred = ", ".join(str(item) for item in route.get("preferred_workflows", []))
    applies_before = ", ".join(str(item) for item in route.get("applies_before", []))
    not_evidence = ", ".join(str(item) for item in route.get("not_evidence_yet", []))
    return "\n".join(
        [
            "[OMH Tool Checkpoint]",
            "schema=omh_generic_tool_checkpoint/v1",
            f"tool_name={_redacted_label(tool_name)}; tool_family={route.get('tool_family')}.",
            f"Before this generic tool ({applies_before}), consider OMH workflow={route.get('primary_workflow')} first.",
            f"preferred_workflows={preferred}.",
            f"next_action={route.get('primary_next_action')}; fallback_action={route.get('fallback_action')}.",
            f"not_evidence_yet={not_evidence}.",
            "Boundary: advisory tool-use context only; not workflow selection, tool invocation, generated output, dispatch, verification, review, CI, merge, or delivery evidence.",
        ]
    )


def _generic_tool_route(kwargs: dict) -> dict[str, object]:
    family = _canonical_tool_family(str(kwargs.get("tool_family", "") or ""))
    tool_name = str(kwargs.get("tool_name", "") or "")
    if not family:
        family = _canonical_tool_family_from_name(tool_name)
    if not family:
        return {}
    for route in generic_tool_checkpoint_routes():
        if route.get("tool_family") == family:
            return route
    return {}


def _canonical_tool_family(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "image": "image_tools",
        "images": "image_tools",
        "image_generation": "image_tools",
        "visual": "image_tools",
        "file": "file_tools",
        "files": "file_tools",
        "document": "file_tools",
        "documents": "file_tools",
        "materials": "file_tools",
        "search": "search_tools",
        "web": "search_tools",
        "browser": "search_tools",
        "research": "search_tools",
        "code": "coding_tools",
        "coding": "coding_tools",
        "executor": "coding_tools",
        "terminal": "coding_tools",
        "shell": "coding_tools",
    }
    if normalized in {"image_tools", "file_tools", "search_tools", "coding_tools"}:
        return normalized
    return aliases.get(normalized, "")


def _canonical_tool_family_from_name(tool_name: str) -> str:
    normalized = tool_name.strip().lower().replace("-", "_")
    families = (
        (
            "image_tools",
            (
                "image",
                "img",
                "visual",
                "render",
                "screenshot",
                "canvas",
            ),
        ),
        (
            "file_tools",
            (
                "file",
                "document",
                "docx",
                "pdf",
                "ppt",
                "slides",
                "sheet",
                "xlsx",
                "spreadsheet",
                "hwp",
                "materials",
            ),
        ),
        (
            "search_tools",
            (
                "web",
                "search",
                "browser",
                "crawl",
                "fetch",
                "open_url",
                "research",
            ),
        ),
        (
            "coding_tools",
            (
                "codex",
                "claude",
                "opencode",
                "coding",
                "executor",
                "apply_patch",
                "git",
            ),
        ),
    )
    for family, markers in families:
        if any(marker in normalized for marker in markers):
            return family
    return ""


def _redacted_label(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in value)
    return safe[:80] or "unknown"
