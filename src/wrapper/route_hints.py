from __future__ import annotations

from ..plugin_bundle.omh.awareness import (
    awareness_generic_tool_checkpoint_payload,
    awareness_route_hint,
    awareness_route_hint_context,
)

CHAT_ROUTE_HINT_SCHEMA_VERSION = "chat_route_hint/v1"
CHAT_ROUTE_HINT_RESPONSE_SCHEMA_VERSION = "chat_route_hint_response/v1"


def build_chat_route_hint_payload(
    message: str,
    *,
    source: str = "generic",
    max_hints: int = 2,
    source_metadata: dict[str, str] | None = None,
    include_prompt_context: bool = False,
) -> dict[str, object]:
    """Return a wrapper-facing route hint without storing or echoing raw prompt text."""
    route_hint = awareness_route_hint(message, max_hints=max_hints)
    generic_tool_checkpoint = _generic_tool_checkpoint()
    hints = [hint for hint in route_hint.get("hints", []) if isinstance(hint, dict)]
    primary_hint = hints[0] if hints else {}
    response = _response_for_hint(primary_hint, hints, source=source, generic_tool_checkpoint=generic_tool_checkpoint)
    payload: dict[str, object] = {
        "schema_version": CHAT_ROUTE_HINT_SCHEMA_VERSION,
        "source": source,
        "message_length": len(message),
        "source_metadata": dict(source_metadata or {}),
        "route_hint": route_hint,
        "generic_tool_checkpoint": generic_tool_checkpoint,
        "chat_response": response,
        "wrapper_contract": {
            "schema_version": "omh_route_hint_wrapper_contract/v1",
            "purpose": "Render a lightweight OMH hint before generic chat/tools when plugin context is unavailable or a wrapper wants an explicit preview.",
            "read_path": "chat_response",
            "state_path": "chat_response.state.route_hint",
            "generic_tool_checkpoint_path": "generic_tool_checkpoint",
            "safe_to_render_without_shell_approval": True,
            "does_not_require_plugin_load": True,
            "next_backend_commands": _next_backend_commands(primary_hint),
        },
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
            "stored_fields": ["message length", "message hash", "matched cue labels", "workflow hint"],
        },
        "claim_boundary": str(route_hint.get("claim_boundary") or ""),
    }
    if include_prompt_context:
        payload["prompt_context"] = awareness_route_hint_context(message, max_hints=max_hints)
        payload["prompt_context_boundary"] = (
            "Prompt context is for Hermes routing guidance only; it is not workflow execution or observed evidence."
        )
    return payload


def _generic_tool_checkpoint() -> dict[str, object]:
    return awareness_generic_tool_checkpoint_payload()


def _checkpoint_body_text(generic_tool_checkpoint: dict[str, object]) -> str:
    body = str(generic_tool_checkpoint.get("body") or "").strip()
    if not body:
        return ""
    return f"Checkpoint: {body}"


def _response_for_hint(
    primary_hint: dict[str, object],
    hints: list[dict[str, object]],
    *,
    source: str,
    generic_tool_checkpoint: dict[str, object],
) -> dict[str, object]:
    checkpoint_body = _checkpoint_body_text(generic_tool_checkpoint)
    if primary_hint:
        workflow = str(primary_hint.get("workflow") or "")
        next_action = str(primary_hint.get("next_action") or "")
        lane = str(primary_hint.get("lane") or "")
        headline = f"[omh] {workflow} looks relevant."
        body = (
            f"I can open `{workflow}` first because this request matches the {lane.replace('_', ' ')} lane. "
            f"Next action: `{next_action}`. This is only a route hint until a workflow is selected and observed."
        )
        if checkpoint_body:
            body = f"{body} {checkpoint_body}"
        actions = [
            {
                "id": "open_workflow",
                "label": f"Open {workflow}",
                "enabled": True,
                "workflow": workflow,
                "next_action": next_action,
                "submit_text": f"./{workflow}",
            },
            {
                "id": "route_for_me",
                "label": "Route for me",
                "enabled": True,
                "backend_command": "omh chat interact",
            },
            {
                "id": "open_picker",
                "label": "Open omh",
                "enabled": True,
                "submit_text": "./omh",
            },
        ]
        render_kind = "workflow_route_hint"
    else:
        workflow = ""
        next_action = "open_picker_or_clarify"
        headline = "[omh] no strong workflow hint yet."
        body = (
            "I do not have a strong OMH workflow hint from this message alone. "
            "Open the workflow picker or ask Hermes to clarify before choosing a workflow."
        )
        if checkpoint_body:
            body = f"{body} {checkpoint_body}"
        actions = [
            {
                "id": "open_picker",
                "label": "Open omh",
                "enabled": True,
                "submit_text": "./omh",
            },
            {
                "id": "clarify",
                "label": "Clarify",
                "enabled": True,
                "backend_command": "omh chat interact --mode clarify",
            },
        ]
        render_kind = "no_route_hint"
    return {
        "schema_version": CHAT_ROUTE_HINT_RESPONSE_SCHEMA_VERSION,
        "kind": render_kind,
        "source": source,
        "headline": headline,
        "body": body,
        "visible_prefix": f"[omh] hint:{workflow}" if workflow else "[omh] hint:none",
        "actions": actions,
        "messenger_rendering": {
            "schema_version": "messenger_route_hint_rendering/v1",
            "profile": source,
            "title": headline,
            "body_text": body,
            "checkpoint_text": checkpoint_body,
            "primary_action": actions[0],
            "secondary_actions": actions[1:],
        },
        "state": {
            "schema_version": "omh_route_hint_state/v1",
            "selected_workflow": workflow,
            "next_action": next_action,
            "route_hint_count": len(hints),
            "route_hint": {
                "schema_version": "omh_route_hint/v1",
                "primary_workflow": workflow,
                "primary_next_action": next_action,
                "hints": hints,
            },
        },
        "claim_boundary": (
            "This response is a preview hint only. It is not workflow selection, execution, generated output, "
            "verification, review, CI, merge, or delivery evidence."
        ),
    }


def _next_backend_commands(primary_hint: dict[str, object]) -> list[dict[str, object]]:
    workflow = str(primary_hint.get("workflow") or "")
    commands = [
        {
            "id": "route_for_me",
            "command": "omh chat interact --source <source> <message>",
            "purpose": "Build the full wrapper interaction envelope from the same event.",
        },
        {
            "id": "open_picker",
            "command": "omh chat interact --source <source> ./omh",
            "purpose": "Open the compact OMH workflow picker.",
        },
    ]
    if workflow:
        commands.insert(
            0,
            {
                "id": "open_workflow",
                "command": f"omh chat interact --source <source> ./{workflow} <message>",
                "purpose": "Open the hinted workflow explicitly when the user chooses it.",
            },
        )
    return commands
