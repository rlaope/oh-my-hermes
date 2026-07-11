from __future__ import annotations

from ..plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS
from .schema import HOOK_EVENT_CAPABILITY_SCHEMA_VERSION, PREPARED_NOT_OBSERVED


def hook_manifest() -> dict[str, object]:
    return {
        "schema_version": HOOK_EVENT_CAPABILITY_SCHEMA_VERSION,
        "plugin_tools": [
            {
                "name": name,
                "supported_by_plugin_bundle": True,
                "supported_by_wrapper_contract": name
                in {
                    "omh_status",
                    "omh_hud",
                    "omh_capabilities",
                    "omh_context",
                    "omh_probe",
                    "omh_recommend",
                    "omh_interact",
                },
                "supported_by_cli_backend": name
                in {"omh_capabilities", "omh_context", "omh_probe", "omh_recommend", "omh_interact"},
                "cli_backend_surface": _cli_backend_surface(name),
                "observed_in_this_environment": False,
            }
            for name in PROVIDED_TOOLS
        ],
        "plugin_hooks": [
            {
                "name": name,
                "supported_by_plugin_bundle": True,
                "payload_fields": _hook_payload_fields(name),
                "claim_boundary": "Hook availability is not proof that Hermes loaded or invoked the plugin.",
                "observed_in_this_environment": False,
            }
            for name in PROVIDED_HOOKS
        ],
        "wrapper_events": [
            _wrapper_event("prompt_submitted", ("source", "message_length", "message_sha256")),
            _wrapper_event("native_command_registered", ("source", "command", "registration_schema")),
            _wrapper_event("native_command_rendered", ("source", "response_kind", "render_kind")),
            _wrapper_event("status_refresh", ("session_id", "run_id")),
            _wrapper_event("executor_opened", ("session_id", "selected_executor_profile", "external_session_ref")),
            _wrapper_event("session_attached", ("session_id", "external_session_ref")),
            _wrapper_event("result_recorded", ("session_id", "result", "evidence_refs")),
            _wrapper_event("verification_requested", ("session_id", "evidence_refs")),
            _wrapper_event("target_topology_changed", ("agent_count", "target_count", "runtime_ref")),
            _wrapper_event("loop_tick_requested", ("loop_id", "queue_id")),
        ],
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "source_refs": [
            "src/plugin_bundle/omh/metadata.py",
            "src/plugin_bundle/omh/awareness.py",
            "src/plugin_bundle/omh/plugin.yaml",
            "src/plugin_bundle/omh/__init__.py",
            "src/plugin_bundle/omh/hooks/verify_hooks.py",
            "src/wrapper/contract.py",
            "src/wrapper/native_commands.py",
        ],
    }


def _wrapper_event(name: str, payload_fields: tuple[str, ...]) -> dict[str, object]:
    return {
        "name": name,
        "payload_fields": list(payload_fields),
        "supported_by_plugin_bundle": False,
        "supported_by_wrapper_contract": True,
        "supported_by_cli_backend": True,
        "observed_in_this_environment": False,
        "claim_boundary": "Wrapper event support is a contract; only recorded wrapper/runtime artifacts prove the event happened.",
    }


def _cli_backend_surface(name: str) -> str:
    if name == "omh_interact":
        return "omh chat interact"
    if name == "omh_capabilities":
        return "omh capabilities"
    if name == "omh_context":
        return "omh context brief"
    if name == "omh_probe":
        return "omh probe"
    if name == "omh_recommend":
        return "omh recommend"
    return ""


def _hook_payload_fields(name: str) -> list[str]:
    if name == "pre_llm_call":
        return ["omh_awareness_primer", "omh_context_brief", "omh_route_hint", "bounded_status_context", "redacted"]
    if name == "pre_tool_call":
        return ["tool_name", "tool_family_hint", "omh_generic_tool_checkpoint", "claim_boundary", "redacted"]
    if name == "on_session_end":
        return ["session_summary", "metadata_only"]
    if name == "pre_verify":
        return ["coding", "attempt", "changed_path_count", "changed_path_categories", "action", "message", "redacted"]
    return []
