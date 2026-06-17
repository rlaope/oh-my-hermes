from __future__ import annotations

from typing import Any


NATIVE_COMMAND_SURFACE_SCHEMA_VERSION = "omh_native_command_surface/v1"
NATIVE_COMMAND_RENDER_SCHEMA_VERSION = "omh_native_command_render/v1"
FALLBACK_CARD_SCHEMA_VERSION = "omh_command_fallback_card/v1"

NATIVE_COMMAND_SOURCES = ("generic", "discord", "slack", "telegram", "hermes")
COMMAND_NAME = "omh"
PARTIAL_PREFIXES = ("./", "/", "./o", "/om")
PICKER_ALIASES = ("./omh", "/omh", "./skills", "/skills")


def build_native_command_surface(source: str = "generic") -> dict[str, object]:
    if source not in NATIVE_COMMAND_SOURCES:
        raise ValueError(f"unsupported native command source: {source}")
    surface = {
        "schema_version": NATIVE_COMMAND_SURFACE_SCHEMA_VERSION,
        "source": source,
        "command": COMMAND_NAME,
        "purpose": "Open the OMH workflow picker from a Hermes chat surface.",
        "entrypoints": {
            "partial_prefixes": list(PARTIAL_PREFIXES),
            "picker_aliases": list(PICKER_ALIASES),
            "direct_skill_names_remain_clean": True,
        },
        "preview_contract": {
            "input": "chat_interaction/v1",
            "response_kind": "command_preview",
            "state_path": "chat_response.state.command_preview",
            "schema_version": "omh_command_preview/v1",
            "only_top_level_suggestions": [COMMAND_NAME],
            "fallback_card_schema": FALLBACK_CARD_SCHEMA_VERSION,
        },
        "fallback_card": _fallback_card(source),
        "registration": _registration_for_source(source),
        "rendering_steps": [
            "Register the platform-native command surface when the platform supports it.",
            "When partial input cannot open native autocomplete, pass the message to `omh chat interact`.",
            "If the response kind is `command_preview`, render the fallback card and primary `Open omh` action.",
            "When the user selects the action, submit `./omh` or `/omh` back through the same wrapper.",
            "Render `chat_response.state.skill_picker.options` only after the picker opens.",
        ],
        "not_evidence": [
            "platform command installed",
            "button rendered",
            "user clicked",
            "workflow selected",
            "plan accepted",
            "executor dispatch",
            "execution",
            "verification",
        ],
        "claim_boundary": "Native command manifests and fallback cards are adapter instructions only; they are not observed platform registration or workflow execution evidence.",
    }
    return surface


def render_native_command_response(interaction: dict[str, object], *, source: str = "generic") -> dict[str, object]:
    if source not in NATIVE_COMMAND_SOURCES:
        raise ValueError(f"unsupported native command source: {source}")
    response = _nested(interaction, "chat_response")
    state = _nested(response, "state")
    kind = str(response.get("kind", ""))
    payload: dict[str, object] = {
        "schema_version": NATIVE_COMMAND_RENDER_SCHEMA_VERSION,
        "source": source,
        "response_kind": kind,
        "thread_key": interaction.get("thread_key", ""),
        "claim_boundary": "Rendered command UI is wrapper guidance until the platform event is observed.",
        "not_evidence": [
            "platform render observed",
            "user selected command",
            "workflow selected",
            "plan accepted",
            "execution",
            "verification",
        ],
    }
    if kind == "command_preview":
        preview = _nested(state, "command_preview")
        suggestion = _first_dict(preview.get("suggestions"))
        insert_text = str(suggestion.get("insert_text") or "./omh")
        payload.update(
            {
                "render_kind": "fallback_card",
                "card": _fallback_card(source, insert_text=insert_text),
                "component": _component_for_source(source, insert_text=insert_text),
            }
        )
        return payload
    if kind == "skill_picker":
        picker = _nested(state, "skill_picker")
        payload.update(
            {
                "render_kind": "workflow_picker",
                "picker_schema": picker.get("schema_version", "omh_skill_picker/v1"),
                "options": picker.get("options", []),
                "component": _picker_component_for_source(source, picker),
            }
        )
        return payload
    payload.update(
        {
            "render_kind": "chat_response",
            "headline": response.get("headline", ""),
            "body": response.get("body", ""),
            "actions": response.get("actions", []),
        }
    )
    return payload


def _fallback_card(source: str, *, insert_text: str | None = None) -> dict[str, object]:
    command = insert_text or ("./omh" if source in {"discord", "generic", "hermes"} else "/omh")
    return {
        "schema_version": FALLBACK_CARD_SCHEMA_VERSION,
        "headline": "Open OMH",
        "body": "Choose `omh` to open the workflow picker. The picker appears before any workflow, plan, handoff, or execution is selected.",
        "primary_action": {
            "id": "show_skill_picker",
            "label": "Open omh",
            "submit_text": command,
            "opens_schema": "omh_skill_picker/v1",
        },
        "secondary_text": "This is a preview card only; no workflow has started.",
    }


def _registration_for_source(source: str) -> dict[str, object]:
    if source == "discord":
        return {
            "schema_version": "discord_application_command_manifest/v1",
            "registration_kind": "slash_command",
            "commands": [
                {
                    "name": COMMAND_NAME,
                    "description": "Open the OMH workflow picker.",
                    "type": "chat_input",
                    "options": [
                        {
                            "name": "request",
                            "description": "Optional request to route after OMH opens.",
                            "type": "string",
                            "required": False,
                        }
                    ],
                }
            ],
            "plain_message_fallback": {
                "trigger": "./",
                "render_contract": FALLBACK_CARD_SCHEMA_VERSION,
            },
        }
    if source == "slack":
        return {
            "schema_version": "slack_command_shortcut_manifest/v1",
            "registration_kind": "slash_command_or_shortcut",
            "slash_commands": [
                {
                    "command": "/omh",
                    "description": "Open the OMH workflow picker.",
                    "usage_hint": "[request]",
                    "payload_target": "omh chat interact --source slack",
                }
            ],
            "shortcuts": [
                {
                    "name": "Open OMH",
                    "callback_id": "omh.open_picker",
                    "description": "Open the OMH workflow picker in the current thread.",
                }
            ],
        }
    if source == "telegram":
        return {
            "schema_version": "telegram_bot_command_menu/v1",
            "registration_kind": "bot_command_menu",
            "bot_commands": [
                {
                    "command": COMMAND_NAME,
                    "description": "Open the OMH workflow picker.",
                }
            ],
            "inline_keyboard_fallback": {
                "text": "Open omh",
                "callback_data": "omh.open_picker",
                "submit_text": "/omh",
            },
        }
    if source == "hermes":
        return {
            "schema_version": "hermes_tui_command_preview/v1",
            "registration_kind": "local_skill_preview",
            "preview_prefix": "./",
            "top_level_command": COMMAND_NAME,
            "opens": "omh_skill_picker/v1",
        }
    return {
        "schema_version": "generic_wrapper_command_manifest/v1",
        "registration_kind": "contract_only",
        "top_level_command": COMMAND_NAME,
        "opens": "omh_skill_picker/v1",
    }


def _component_for_source(source: str, *, insert_text: str) -> dict[str, object]:
    if source == "discord":
        return {
            "kind": "discord_message_components",
            "buttons": [
                {
                    "custom_id": "omh.open_picker",
                    "label": "Open omh",
                    "style": "primary",
                    "submit_text": insert_text,
                }
            ],
        }
    if source == "slack":
        return {
            "kind": "slack_blocks",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "*Open OMH*"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "omh.open_picker",
                            "text": {"type": "plain_text", "text": "Open omh"},
                            "value": insert_text,
                        }
                    ],
                },
            ],
        }
    if source == "telegram":
        return {
            "kind": "telegram_inline_keyboard",
            "reply_markup": {
                "inline_keyboard": [[{"text": "Open omh", "callback_data": "omh.open_picker"}]],
            },
            "submit_text": insert_text,
        }
    if source == "hermes":
        return {
            "kind": "hermes_tui_preview_row",
            "rows": [{"label": COMMAND_NAME, "submit_text": insert_text, "opens": "omh_skill_picker/v1"}],
        }
    return {
        "kind": "generic_button_card",
        "buttons": [{"label": "Open omh", "submit_text": insert_text}],
    }


def _picker_component_for_source(source: str, picker: dict[str, object]) -> dict[str, object]:
    options = [
        {"label": str(option.get("label", "")), "value": str(option.get("id", ""))}
        for option in _list_of_dicts(picker.get("options"))
    ]
    if source == "discord":
        return {"kind": "discord_select_menu", "custom_id": "omh.choose_workflow", "options": options}
    if source == "slack":
        return {"kind": "slack_static_select", "action_id": "omh.choose_workflow", "options": options}
    if source == "telegram":
        return {
            "kind": "telegram_inline_keyboard",
            "reply_markup": {
                "inline_keyboard": [[{"text": option["label"], "callback_data": f"omh.workflow:{option['value']}"}] for option in options]
            },
        }
    if source == "hermes":
        return {"kind": "hermes_tui_command_list", "rows": options}
    return {"kind": "generic_select", "options": options}


def _nested(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_dict(value: object) -> dict[str, Any]:
    items = _list_of_dicts(value)
    return items[0] if items else {}
