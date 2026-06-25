from __future__ import annotations

from ..version import __version__
from ..capabilities.families import capability_family_cards
from ..doctor import doctor_ok, recommended_next_action, run_doctor
from ..paths import OmhPaths
from ..probe import probe_capabilities

QUICKSTART_CARD_SCHEMA_VERSION = "omh_quickstart_card/v1"


def build_quickstart_card(paths: OmhPaths, *, source: str = "hermes") -> dict[str, object]:
    checks = run_doctor(paths)
    probe = probe_capabilities(paths, include_roadmap=True)
    capabilities = _capabilities_by_name(probe.get("capabilities", []))
    doctor_status = _doctor_status(checks)
    plugin_bridge = _plugin_bridge_status(probe, capabilities)
    wrapper_usage = _capability_status(capabilities, "wrapper_metadata", default_status="missing")
    runtime_observed = bool(probe.get("plugin_runtime_observed"))
    runtime_active = bool(probe.get("plugin_runtime_active"))

    return {
        "schema_version": QUICKSTART_CARD_SCHEMA_VERSION,
        "status": "ready" if doctor_status["blocking"] == 0 else "needs_attention",
        "omh_version": __version__,
        "source": str(source or "hermes"),
        "paths": {
            "omh_home": str(paths.omh_home),
            "hermes_home": str(paths.hermes_home),
            "skills_dir": str(paths.skills_dir),
            "hermes_config": str(paths.hermes_config_path),
        },
        "local_status": {
            "doctor": doctor_status,
            "plugin_bridge": plugin_bridge,
            "plugin_runtime_observed": runtime_observed,
            "plugin_runtime_active": runtime_active,
            "wrapper_usage": wrapper_usage,
            "target_topology": probe.get("target_topology", {}),
            "native_integration_claim_ready": bool(probe.get("native_integration_claim_ready")),
        },
        "first_five_minutes": [
            "Restart or reload Hermes Agent after setup.",
            "Ask Hermes what OMH can do, or paste a plain request and let Hermes route it.",
            "For coding work, ask for request-to-handoff after the scope is clear.",
        ],
        "first_use_family_cards": capability_family_cards(),
        "chat_prompts": [
            {
                "label": "safe feature work",
                "prompt": "Use OMH request-to-handoff for: I want to safely add a feature to this repo.",
                "expected_workflow": "request-to-handoff",
            },
            {
                "label": "image summary card",
                "prompt": "Use OMH img-summary for: summarize this PR as a shareable image card.",
                "expected_workflow": "img-summary",
            },
            {
                "label": "ambitious loop",
                "prompt": "Use OMH loop for: improve this repo's first-run experience until the next bottleneck is verified.",
                "expected_workflow": "loop",
            },
        ],
        "wrapper_actions": [
            {
                "id": "open_workflow_picker",
                "label": "Open OMH picker",
                "surface": str(source or "hermes"),
                "copy": "Show ./omh or the compact OMH workflow picker.",
                "records_evidence": False,
            },
            {
                "id": "record_wrapper_usage",
                "label": "Record wrapper usage when Hermes uses OMH",
                "surface": str(source or "hermes"),
                "copy": "Record route/session metadata only after the wrapper has actually used an OMH workflow.",
                "records_evidence": True,
            },
            {
                "id": "observe_plugin_runtime",
                "label": "Observe Hermes plugin runtime",
                "surface": "hermes-host",
                "copy": "Record host-supplied plugin load/use evidence only after Hermes reports it.",
                "records_evidence": True,
            },
        ],
        "not_evidence_yet": [
            "A ready local plugin bridge is not proof that Hermes loaded or used the plugin.",
            "A prepared handoff is not code execution, review, CI, merge readiness, or merge evidence.",
            "A wrapper card is not runtime evidence until matching observation records exist.",
        ],
        "operator_next_actions": _operator_next_actions(checks, probe),
        "capability_gap_roadmap": probe.get("capability_gap_roadmap", {}),
        "claim_boundary": probe.get("claim_boundary", ""),
    }


def _capabilities_by_name(capabilities: object) -> dict[str, dict[str, object]]:
    if not isinstance(capabilities, list):
        return {}
    by_name: dict[str, dict[str, object]] = {}
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        name = str(capability.get("name", "")).strip()
        if name:
            by_name[name] = capability
    return by_name


def _doctor_status(checks: list[object]) -> dict[str, object]:
    blocking = [
        str(getattr(check, "name", "unknown"))
        for check in checks
        if not bool(getattr(check, "ok", False)) and str(getattr(check, "severity", "")) == "blocking"
    ]
    warnings = [
        str(getattr(check, "name", "unknown"))
        for check in checks
        if str(getattr(check, "severity", "")) == "warning"
    ]
    return {
        "status": "ok" if doctor_ok(checks) else "needs_attention",
        "passing": sum(1 for check in checks if bool(getattr(check, "ok", False))),
        "total": len(checks),
        "blocking": len(blocking),
        "warnings": len(warnings),
        "blocking_checks": blocking,
        "warning_checks": warnings,
        "recommended_next_action": recommended_next_action(checks),
    }


def _plugin_bridge_status(probe: dict[str, object], capabilities: dict[str, dict[str, object]]) -> dict[str, object]:
    bundle = _capability_status(capabilities, "omh_plugin_bundle")
    import_smoke = _capability_status(capabilities, "plugin_import_smoke")
    register_smoke = _capability_status(capabilities, "plugin_register_smoke")
    distribution_ready = bool(probe.get("plugin_distribution_ready"))
    if distribution_ready and import_smoke["status"] == "available" and register_smoke["status"] == "available":
        status = "ready_locally"
        message = "Plugin bridge is installed and passed local import/register smoke."
    elif bundle["status"] == "missing":
        status = "missing"
        message = "Plugin bridge is not installed locally."
    else:
        status = "needs_attention"
        message = "Plugin bridge exists but local smoke evidence is incomplete."
    return {
        "status": status,
        "distribution_ready": distribution_ready,
        "bundle": bundle,
        "import_smoke": import_smoke,
        "register_smoke": register_smoke,
        "message": message,
    }


def _capability_status(
    capabilities: dict[str, dict[str, object]],
    name: str,
    *,
    default_status: str = "unknown",
) -> dict[str, object]:
    capability = capabilities.get(name, {})
    if not capability:
        return {"status": default_status, "message": "", "evidence": ""}
    return {
        "status": str(capability.get("status", default_status)),
        "message": str(capability.get("message", "")),
        "evidence": str(capability.get("evidence", "")),
    }


def _operator_next_actions(checks: list[object], probe: dict[str, object]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    next_action = recommended_next_action(checks)
    if next_action:
        actions.append({"kind": "doctor", "label": "Doctor next action", "next": next_action})
    roadmap = probe.get("capability_gap_roadmap", {})
    if isinstance(roadmap, dict):
        for action in roadmap.get("next_actions", [])[:3]:
            if not isinstance(action, dict):
                continue
            label = str(action.get("label", "")).strip() or "Capability next action"
            next_step = str(action.get("next_step") or action.get("command") or action.get("description") or "").strip()
            if next_step:
                actions.append({"kind": str(action.get("kind", "roadmap")), "label": label, "next": next_step})
    return actions
