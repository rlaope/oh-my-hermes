from __future__ import annotations

import argparse
import os
import sys

from .. import __version__
from ..doctor import doctor_ok, recommended_next_action, run_doctor
from ..probe import probe_capabilities
from .common import _paths, _print_json, _wants_json

QUICKSTART_CARD_SCHEMA_VERSION = "omh_quickstart_card/v1"


def cmd_quickstart(args: argparse.Namespace) -> int:
    card = build_quickstart_card(args)
    if _wants_json(args):
        _print_json(card)
    else:
        _print_quickstart_card(card)
    return 0


def build_quickstart_card(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    checks = run_doctor(paths)
    probe = probe_capabilities(paths, include_roadmap=True)
    capabilities = _capabilities_by_name(probe.get("capabilities", []))
    doctor_status = _doctor_status(checks)
    plugin_bridge = _plugin_bridge_status(probe, capabilities)
    wrapper_usage = _capability_status(capabilities, "wrapper_metadata", default_status="missing")
    runtime_observed = bool(probe.get("plugin_runtime_observed"))
    runtime_active = bool(probe.get("plugin_runtime_active"))
    source = str(getattr(args, "source", "hermes") or "hermes")

    card = {
        "schema_version": QUICKSTART_CARD_SCHEMA_VERSION,
        "status": "ready" if doctor_status["blocking"] == 0 else "needs_attention",
        "omh_version": __version__,
        "source": source,
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
            "Ask Hermes: Use OMH request-to-handoff for: I want to safely add a feature to this repo.",
            "If you want to choose manually, type ./omh or ask Hermes what OMH workflows are available.",
        ],
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
                "surface": source,
                "copy": "Show ./omh or the compact OMH workflow picker.",
                "records_evidence": False,
            },
            {
                "id": "record_wrapper_usage",
                "label": "Record wrapper usage when Hermes uses OMH",
                "surface": source,
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
        "claim_boundary": probe.get("claim_boundary", ""),
    }
    return card


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


def _print_quickstart_card(card: dict[str, object]) -> None:
    use_color = _use_color()
    status = str(card.get("status", "unknown"))
    local_status = card.get("local_status", {})
    if not isinstance(local_status, dict):
        local_status = {}
    doctor = local_status.get("doctor", {})
    plugin_bridge = local_status.get("plugin_bridge", {})
    wrapper_usage = local_status.get("wrapper_usage", {})
    target_topology = local_status.get("target_topology", {})
    if not isinstance(doctor, dict):
        doctor = {}
    if not isinstance(plugin_bridge, dict):
        plugin_bridge = {}
    if not isinstance(wrapper_usage, dict):
        wrapper_usage = {}
    if not isinstance(target_topology, dict):
        target_topology = {}

    print(_color("OMH quickstart", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Status: {_status_label(status, use_color)}")
    print(f"  OMH version: {card.get('omh_version', '')}")
    print(f"  Local install: {doctor.get('status', 'unknown')} ({doctor.get('passing', 0)}/{doctor.get('total', 0)} checks)")
    print(f"  Plugin bridge: {_plugin_bridge_label(str(plugin_bridge.get('status', 'unknown')))}")
    print(f"  Live Hermes plugin use: {_observed_label(bool(local_status.get('plugin_runtime_active')), positive='observed', negative='not observed yet')}")
    print(f"  Wrapper usage: {_wrapper_usage_label(str(wrapper_usage.get('status', 'missing')))}")
    print(
        "  Target topology: "
        f"{target_topology.get('mode', 'unknown')} "
        f"({target_topology.get('known_target_count', 0)} known target(s))"
    )

    print(_color("Do this in Hermes", "1;32", use_color))
    for line in _string_list(card.get("first_five_minutes", [])):
        print(f"  - {line}")

    print(_color("Try one prompt", "1;32", use_color))
    for prompt in _dict_list(card.get("chat_prompts", []))[:3]:
        print(f"  - {prompt.get('label', 'prompt')}: {prompt.get('prompt', '')}")

    print(_color("Still not evidence", "1;32", use_color))
    for line in _string_list(card.get("not_evidence_yet", [])):
        print(f"  - {line}")

    actions = _dict_list(card.get("operator_next_actions", []))
    if actions:
        print(_color("Operator next actions", "1;32", use_color))
        for action in actions[:4]:
            print(f"  - {action.get('label', 'Next')}: {action.get('next', '')}")
    print("  For machine-readable output, rerun with `--json`.")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _status_label(status: str, use_color: bool) -> str:
    if status == "ready":
        return _color("ready", "1;32", use_color)
    if status == "needs_attention":
        return _color("needs attention", "1;33", use_color)
    return status


def _plugin_bridge_label(status: str) -> str:
    if status == "ready_locally":
        return "ready locally"
    return status.replace("_", " ")


def _wrapper_usage_label(status: str) -> str:
    if status == "available":
        return "recorded"
    if status == "missing":
        return "not recorded yet"
    return status


def _observed_label(observed: bool, *, positive: str, negative: str) -> str:
    return positive if observed else negative


def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _add_quickstart_commands(sub) -> None:
    quickstart = sub.add_parser(
        "quickstart",
        help="Show the first-use OMH/Hermes path and current evidence boundaries.",
    )
    quickstart.add_argument("--json", action="store_true", help="Print the full machine-readable quickstart card.")
    quickstart.add_argument(
        "--source",
        default="hermes",
        choices=("hermes", "discord", "slack", "telegram", "terminal", "wrapper"),
        help="Surface that will render the card.",
    )
    quickstart.set_defaults(func=cmd_quickstart)
