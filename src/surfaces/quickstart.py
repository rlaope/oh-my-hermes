from __future__ import annotations

from ..version import __version__
from ..capabilities.families import capability_family_cards
from ..doctor import doctor_ok, recommended_next_action, run_doctor
from ..paths import OmhPaths
from ..probe import probe_capabilities
from .natural_language_starters import natural_language_starters

QUICKSTART_CARD_SCHEMA_VERSION = "omh_quickstart_card/v1"

FIRST_VALUE_PACKS: tuple[dict[str, object], ...] = (
    {
        "id": "frontend_rescue",
        "label": "Frontend Rescue",
        "problem": (
            "A web UI feels generic, AI-looking, broken, inaccessible, "
            "or fragile across viewports."
        ),
        "prompt": (
            "Use OMH frontend for: make this page feel natural, "
            "fix broken responsive layout, and require visual QA."
        ),
        "primary_workflows": ("frontend", "design-quality-gate", "visual-qa", "accessibility-audit"),
        "harness_surfaces": (),
        "conceptual_surfaces": (),
        "family_ids": ("create_materials_and_visuals",),
        "outcome": (
            "Frontend brief, design-system contract, state/viewport matrix, "
            "implementation handoff, and visual QA gate."
        ),
        "evidence_boundary": (
            "Prepared frontend guidance is not implementation, browser verification, "
            "accessibility PASS, deployment, or visual QA evidence."
        ),
    },
    {
        "id": "repo_first_win",
        "label": "Repo First-Win",
        "problem": (
            "A new repo is installed but the user does not know the first "
            "valuable, safe PR-sized task."
        ),
        "prompt": (
            "Use OMH codebase-onboarding for: find the first safe high-value "
            "improvement in this repo."
        ),
        "primary_workflows": ("codebase-onboarding", "codegraph-refresh", "verification-gate"),
        "harness_surfaces": (),
        "conceptual_surfaces": ("request-to-handoff",),
        "family_ids": ("plan_and_decide", "delegate_coding_and_ship"),
        "outcome": "Repo map, reading path, risk map, first-task runway, verification commands, and handoff readiness.",
        "evidence_boundary": (
            "A first-task runway is planning evidence; it is not code execution, "
            "tests, review, CI, or merge evidence."
        ),
    },
    {
        "id": "failure_to_fix",
        "label": "Failure-to-Fix",
        "problem": "Builds, deploys, Pages, CI, DCO, tests, or hidden failures keep blocking delivery.",
        "prompt": (
            "Use OMH build-failure-triage for: diagnose this failing deploy "
            "or CI log and prepare the smallest fix path."
        ),
        "primary_workflows": ("build-failure-triage", "failure-signal-audit", "agent-debug", "verification-gate"),
        "harness_surfaces": (),
        "conceptual_surfaces": (),
        "family_ids": ("operate_and_observe", "delegate_coding_and_ship"),
        "outcome": (
            "Failure classification, minimal fix plan, regression command, "
            "and evidence-aware implementation handoff."
        ),
        "evidence_boundary": (
            "Triage is not a fix, rerun, CI pass, deployment, or merge until "
            "observed evidence proves those steps."
        ),
    },
    {
        "id": "visual_deliverable",
        "label": "Visual Deliverable",
        "problem": "A PR, release, report, deck, PDF, or package needs to become a polished shareable artifact.",
        "prompt": (
            "Use OMH img-summary for: turn this PR or release into a shareable "
            "image card and delivery package."
        ),
        "primary_workflows": ("img-summary", "materials-package", "report-package", "deliverable-package"),
        "harness_surfaces": (),
        "conceptual_surfaces": (),
        "family_ids": ("create_materials_and_visuals",),
        "outcome": "Prompt card, package plan, export checklist, delivery boundary, and visual/publishing readiness.",
        "evidence_boundary": (
            "A prompt or package plan is not generated media, exported files, "
            "visual QA, publication, or delivery evidence."
        ),
    },
    {
        "id": "toolbelt_readiness",
        "label": "Toolbelt Readiness",
        "problem": "A workflow depends on MCP, CLIs, connectors, credentials, executors, or local host readiness.",
        "prompt": (
            "Use OMH toolbelt-readiness for: tell me what tools, MCP hosts, "
            "or credentials are missing before this workflow."
        ),
        "primary_workflows": ("doctor", "ops-observability-card"),
        "harness_surfaces": ("toolbelt-readiness", "executor-runtime-readiness"),
        "conceptual_surfaces": (),
        "family_ids": ("operate_and_observe", "delegate_coding_and_ship"),
        "outcome": "Installed/missing/credential matrix, safe next setup action, and readiness evidence boundary.",
        "evidence_boundary": (
            "A readiness card is not connector invocation, credential validity, "
            "host load, or workflow execution evidence."
        ),
    },
    {
        "id": "cto_product_loop",
        "label": "CTO/Product Loop",
        "problem": "A roadmap, launch, risky feature, or product operation needs leadership-level tradeoff review.",
        "prompt": (
            "Use OMH cto-loop for: review this launch across roadmap, "
            "architecture, delivery risk, QA, security, and ops."
        ),
        "primary_workflows": ("cto-loop", "strategy-brief", "feedback-triage", "deploy-and-monitor"),
        "harness_surfaces": (),
        "conceptual_surfaces": (),
        "family_ids": ("learn_and_gather", "delegate_coding_and_ship", "operate_and_observe"),
        "outcome": "Leadership loop, risks, decisions, follow-up handoffs, release readiness, and status boundaries.",
        "evidence_boundary": (
            "A leadership loop is not executor dispatch, implementation, "
            "production deploy, monitoring proof, or release approval evidence."
        ),
    },
)


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
            "For coding work, describe the outcome and constraints; Hermes can prepare a handoff after the scope is clear.",
        ],
        "first_value_packs": first_value_packs(),
        "first_use_family_cards": capability_family_cards(),
        "natural_language_starters": natural_language_starters(),
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
                "prompt": (
                    "Use OMH loop for: improve this repo's first-run experience "
                    "until the next bottleneck is verified."
                ),
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


def first_value_packs() -> list[dict[str, object]]:
    return [_pack_payload(pack) for pack in FIRST_VALUE_PACKS]


def _pack_payload(pack: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(pack["id"]),
        "label": str(pack["label"]),
        "problem": str(pack["problem"]),
        "prompt": str(pack["prompt"]),
        "primary_workflows": _string_tuple(pack.get("primary_workflows", ()), field="primary_workflows"),
        "harness_surfaces": _string_tuple(pack.get("harness_surfaces", ()), field="harness_surfaces"),
        "conceptual_surfaces": _string_tuple(pack.get("conceptual_surfaces", ()), field="conceptual_surfaces"),
        "family_ids": _string_tuple(pack.get("family_ids", ()), field="family_ids"),
        "outcome": str(pack["outcome"]),
        "evidence_boundary": str(pack["evidence_boundary"]),
    }


def _string_tuple(value: object, *, field: str) -> list[str]:
    if not isinstance(value, tuple):
        raise TypeError(f"first-value pack {field} must be a tuple")
    return [str(item) for item in value if str(item)]


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
