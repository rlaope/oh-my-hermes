from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omh.ingress import extract_message_text, extract_source_metadata  # noqa: E402
from omh.wrapper.contract import (  # noqa: E402
    INTERACTION_MODES,
    build_chat_interaction_payload,
    build_chat_status_interaction,
    usage_trace_payload,
)
from omh.wrapper.native_commands import build_native_command_surface, render_native_command_response  # noqa: E402
from omh.wrapper.route_hints import build_chat_route_hint_payload  # noqa: E402
from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler  # noqa: E402


SCHEMA_VERSION = "wrapper_adapter_shim/v1"


def run_shim(source: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Render a {source} Hermes chat fixture.")
    parser.add_argument(
        "event_json",
        nargs="?",
        default=str(_default_fixture(source)),
        help="Fixture event JSON path for the Hermes chat contract example.",
    )
    parser.add_argument("--mode", choices=INTERACTION_MODES, default="auto")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--route-hint",
        action="store_true",
        help="Render a metadata-only route-hint card from the fixture event instead of a full interaction.",
    )
    parser.add_argument(
        "--plugin-interact",
        action="store_true",
        help=(
            "Render the fixture through the managed plugin's omh_interact tool. "
            "By default this uses temporary OMH/Hermes homes so the example does not mutate real user state."
        ),
    )
    parser.add_argument(
        "--status-json",
        default=None,
        help="Optional delegated_coding_status/v1 JSON to render as a status card instead of routing the event.",
    )
    parser.add_argument(
        "--omh-home",
        default=None,
        help="Optional OMH home for --plugin-interact. Defaults to an isolated temporary directory.",
    )
    parser.add_argument(
        "--hermes-home",
        default=None,
        help="Optional Hermes home for --plugin-interact. Defaults to an isolated temporary directory.",
    )
    parser.add_argument(
        "--no-record-session",
        action="store_true",
        help="For --plugin-interact, render without recording the metadata-only wrapper session.",
    )
    args = parser.parse_args(argv)

    selected_modes = sum(bool(flag) for flag in (args.route_hint, args.status_json, args.plugin_interact))
    if selected_modes > 1:
        parser.error("--route-hint, --status-json, and --plugin-interact are mutually exclusive")

    if args.status_json:
        status_payload = _read_json(Path(args.status_json))
        interaction = build_chat_status_interaction(status_payload, source=source)
    elif args.route_hint:
        event = _read_json(Path(args.event_json))
        message = extract_message_text(event)
        payload = build_chat_route_hint_payload(
            message,
            source=source,
            max_hints=args.limit,
            source_metadata=extract_source_metadata(event),
        )
        print(json.dumps(_render_route_hint(source, payload), indent=2, sort_keys=True))
        return 0
    elif args.plugin_interact:
        event = _read_json(Path(args.event_json))
        interaction = _plugin_interaction(
            source,
            event,
            fixture=Path(args.event_json),
            mode=args.mode,
            limit=args.limit,
            omh_home=args.omh_home,
            hermes_home=args.hermes_home,
            record_session=not args.no_record_session,
        )
        print(json.dumps(_render_plugin_interaction(source, interaction), indent=2, sort_keys=True))
        return 0
    else:
        event = _read_json(Path(args.event_json))
        interaction = build_chat_interaction_payload(event, source=source, mode=args.mode, limit=args.limit)
    print(json.dumps(_render(source, interaction), indent=2, sort_keys=True))
    return 0


def _default_fixture(source: str) -> Path:
    filename_by_source = {
        "discord": "discord-safe-feature.json",
        "slack": "slack-risky-refactor.json",
        "telegram": "telegram-command-preview.json",
    }
    filename = filename_by_source.get(source, "discord-safe-feature.json")
    return Path(__file__).resolve().parent / "wrapper-events" / filename


def _read_json(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must be a JSON object: {path}")
    return payload


def _render_route_hint(source: str, payload: dict[str, object]) -> dict[str, object]:
    response = _nested(payload, "chat_response")
    state = _nested(response, "state")
    rendering = _nested(response, "messenger_rendering")
    source_metadata = _nested(payload, "source_metadata")
    next_action = str(state.get("next_action", "open_picker_or_clarify"))
    usage_trace = usage_trace_payload(
        kind=str(response.get("kind") or "workflow_route_hint"),
        phase="route_hint",
        next_action=next_action,
        state=state,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "thread_key": _thread_key(source, source_metadata),
        "mode": "route_hint",
        "next_action": next_action,
        "redaction_policy": "metadata_only",
        "source_metadata": source_metadata,
        "response": {
            "kind": response.get("kind", ""),
            "headline": response.get("headline", ""),
            "plain_headline": response.get("headline", ""),
            "body": response.get("body", ""),
            "body_text": rendering.get("body_text", response.get("body", "")),
            "body_text_source": "messenger_rendering.body_text",
            "phase": "route_hint",
            "claim_boundary": response.get("claim_boundary", payload.get("claim_boundary", "")),
        },
        "route_hint": payload.get("route_hint", {}),
        "generic_tool_checkpoint": payload.get("generic_tool_checkpoint", {}),
        "wrapper_contract": payload.get("wrapper_contract", {}),
        "privacy": payload.get("privacy", {}),
        "usage_trace": usage_trace,
        "messenger_rendering": rendering,
        "actions": [
            {
                "id": action.get("id", ""),
                "label": action.get("label", ""),
                "enabled": action.get("enabled", False),
                "submit_text": action.get("submit_text", ""),
                "backend_command": action.get("backend_command", ""),
            }
            for action in _list_of_dicts(response.get("actions", []))
        ],
        "native_command_registration": build_native_command_surface(source),
        "native_render": None,
        "status_card": None,
        "not_evidence_until_observed": [
            "workflow_selection",
            "workflow_execution",
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "delivery",
        ],
    }


def _plugin_interaction(
    source: str,
    event: dict[str, Any],
    *,
    fixture: Path,
    mode: str,
    limit: int,
    omh_home: str | None,
    hermes_home: str | None,
    record_session: bool,
) -> dict[str, Any]:
    message = extract_message_text(event)
    source_metadata = extract_source_metadata(event)
    if omh_home and hermes_home:
        return _plugin_interaction_with_homes(
            source,
            message,
            source_metadata,
            fixture=fixture,
            mode=mode,
            limit=limit,
            omh_home=omh_home,
            hermes_home=hermes_home,
            record_session=record_session,
            state_scope="caller_supplied",
        )

    with tempfile.TemporaryDirectory(prefix="omh-plugin-interact.") as temp_root:
        root = Path(temp_root)
        return _plugin_interaction_with_homes(
            source,
            message,
            source_metadata,
            fixture=fixture,
            mode=mode,
            limit=limit,
            omh_home=str(root / ".omh"),
            hermes_home=str(root / ".hermes"),
            record_session=record_session,
            state_scope="temporary_example",
        )


def _plugin_interaction_with_homes(
    source: str,
    message: str,
    source_metadata: dict[str, Any],
    *,
    fixture: Path,
    mode: str,
    limit: int,
    omh_home: str,
    hermes_home: str,
    record_session: bool,
    state_scope: str,
) -> dict[str, Any]:
    payload = json.loads(
        omh_interact_handler(
            {
                "message": message,
                "source": source,
                "mode": mode,
                "limit": limit,
                "record_session": record_session,
                "source_metadata": source_metadata,
                "omh_home": omh_home,
                "hermes_home": hermes_home,
                "observation": {
                    "host": f"{source}-hermes-wrapper-example",
                    "session_id": f"{source}-plugin-interact-example",
                    "event": "tool_call",
                    "evidence_ref": f"fixture:{fixture.as_posix()}#omh_interact",
                },
            }
        )
    )
    payload["example_runtime"] = {
        "schema_version": "omh_plugin_interact_example_runtime/v1",
        "state_scope": state_scope,
        "real_user_state_mutated": state_scope != "temporary_example",
        "tool": "omh_interact",
    }
    return payload


def _render_plugin_interaction(source: str, interaction: dict[str, Any]) -> dict[str, object]:
    rendered = _render(source, interaction)
    response = _nested(interaction, "chat_response")
    wrapper_session = interaction.get("wrapper_session") if isinstance(interaction.get("wrapper_session"), dict) else {}
    provenance = (
        wrapper_session.get("record_provenance", {})
        if isinstance(wrapper_session, dict) and isinstance(wrapper_session.get("record_provenance"), dict)
        else {}
    )
    claim_boundary = (
        str(interaction.get("claim_boundary") or "")
        or str(wrapper_session.get("claim_boundary") or "")
        or str(response.get("claim_boundary") or "")
    )
    rendered["mode"] = "plugin_interact"
    rendered["plugin_interact"] = {
        "schema_version": "omh_plugin_interact_render/v1",
        "tool": "omh_interact",
        "source_backend": interaction.get("source_backend", "package_backend"),
        "wrapper_session_recorded": bool(wrapper_session.get("recorded")) if isinstance(wrapper_session, dict) else False,
        "wrapper_session_status": wrapper_session.get("session_status", "") if isinstance(wrapper_session, dict) else "",
        "record_provenance": provenance,
        "plugin_host_observation": interaction.get("plugin_host_observation", {}),
        "example_runtime": interaction.get("example_runtime", {}),
        "claim_boundary": claim_boundary,
    }
    rendered["not_evidence_until_observed"] = [
        "workflow_execution",
        "executor_dispatch",
        "executor_result",
        "verification",
        "review",
        "ci",
        "merge",
    ]
    return rendered


def _render(source: str, interaction: dict[str, object]) -> dict[str, object]:
    response = _nested(interaction, "chat_response")
    state = _nested(response, "state")
    rendering = _nested(response, "messenger_rendering")
    body_text = rendering.get("body_text")
    if isinstance(body_text, str):
        rendered_body_text = body_text
        body_text_source = "messenger_rendering.body_text"
    else:
        rendered_body_text = str(response.get("body", ""))
        body_text_source = "missing_messenger_rendering.body_text"
    status_card = response.get("status_card") or interaction.get("status_card")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "thread_key": interaction.get("thread_key", ""),
        "mode": interaction.get("mode", ""),
        "next_action": interaction.get("next_action", ""),
        "redaction_policy": interaction.get("redaction_policy", "metadata_only"),
        "source_metadata": interaction.get("source_metadata", {}),
        "response": {
            "kind": response.get("kind", ""),
            "headline": response.get("headline", ""),
            "plain_headline": response.get("plain_headline", ""),
            "body": response.get("body", ""),
            "body_text": rendered_body_text,
            "body_text_source": body_text_source,
            "phase": state.get("phase", ""),
            "claim_boundary": response.get("claim_boundary", ""),
        },
        "usage_trace": response.get("usage_trace", {}),
        "messenger_rendering": rendering,
        "actions": [
            {
                "id": action.get("id", ""),
                "label": action.get("label", ""),
                "enabled": action.get("enabled", False),
                "style": action.get("style", ""),
            }
            for action in _list_of_dicts(response.get("actions", []))
        ],
        "native_command_registration": build_native_command_surface(source),
        "native_render": render_native_command_response(interaction, source=source),
        "status_card": status_card if isinstance(status_card, dict) else None,
        "not_evidence_until_observed": [
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "ci",
            "merge",
        ],
    }


def _nested(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _thread_key(source: str, metadata: dict[str, Any]) -> str:
    channel = str(metadata.get("channel_ref") or "unknown")
    event_id = str(metadata.get("source_event_id") or "unknown")
    return f"{source}:{channel}:{event_id}"
