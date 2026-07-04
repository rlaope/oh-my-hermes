from __future__ import annotations


CAPABILITY_GAP_ROADMAP_SCHEMA_VERSION = "omh_capability_gap_roadmap/v1"
BASELINE_PRODUCT_CAPABILITIES = ("managed_skills", "external_skill_dirs", "target_registry", "omh_plugin_bundle")
PLUGIN_SMOKE_CAPABILITIES = ("plugin_import_smoke", "plugin_register_smoke")
OPTIONAL_HOST_CAPABILITIES = ("native_hooks", "apps", "native_skill_metadata", "mcp_host_config")


def build_capability_gap_roadmap(probe_payload: dict[str, object]) -> dict[str, object]:
    capabilities = _capability_map(probe_payload)
    actions: list[dict[str, object]] = []

    baseline_gaps = [
        _gap_item(capabilities, name, category="product_gap", severity="blocking")
        for name in BASELINE_PRODUCT_CAPABILITIES
        if _status(capabilities, name) not in {"available"}
    ]
    baseline_gaps = [item for item in baseline_gaps if item]
    if baseline_gaps:
        actions.append(
            {
                "id": "run_setup",
                "kind": "product_gap",
                "priority": 10,
                "label": "Run OMH setup",
                "why": "Managed skills, Hermes registration, target registry, or plugin bridge evidence is missing.",
                "command": "omh setup",
                "boundary": "Setup prepares and registers local OMH workflow surfaces; it is not workflow execution evidence.",
                "capabilities": [item["capability"] for item in baseline_gaps],
            }
        )

    plugin_smoke_gaps = [
        _gap_item(capabilities, name, category="product_gap", severity="repair")
        for name in PLUGIN_SMOKE_CAPABILITIES
        if _status(capabilities, name) == "missing"
    ]
    plugin_smoke_gaps = [item for item in plugin_smoke_gaps if item]
    if plugin_smoke_gaps:
        actions.append(
            {
                "id": "repair_plugin_bridge",
                "kind": "product_gap",
                "priority": 25,
                "label": "Repair the managed OMH plugin bridge",
                "why": "The managed plugin bundle exists, but its local current-package, import, or register smoke check is failing.",
                "command": "omh setup",
                "fallback_command": "omh setup --force",
                "boundary": "Repairing the local plugin bridge is not proof that Hermes loaded it or that any workflow executed.",
                "capabilities": [item["capability"] for item in plugin_smoke_gaps],
            }
        )

    evidence_gaps: list[dict[str, object]] = []
    if probe_payload.get("plugin_distribution_ready") and not probe_payload.get("plugin_runtime_active"):
        evidence_gaps.append(
            _gap_item(
                capabilities,
                "plugin_runtime_observed",
                category="evidence_gap",
                severity="non_blocking",
            )
        )
        actions.append(
            {
                "id": "observe_plugin_runtime",
                "kind": "evidence_gap",
                "priority": 20,
                "label": "Record Hermes plugin runtime observation",
                "why": "The OMH plugin bundle is locally installed, but no host-supplied active Hermes plugin event is recorded yet.",
                "command": "omh plugin observe-host --event plugin_load --host hermes --evidence-ref <host-log-or-wrapper-event>",
                "boundary": "A plugin observation proves only that host plugin event, not coding execution, review, CI, or merge.",
                "capabilities": ["plugin_runtime_observed"],
            }
        )

    if _status(capabilities, "wrapper_metadata") != "available":
        evidence_gaps.append(
            _gap_item(
                capabilities,
                "wrapper_metadata",
                category="evidence_gap",
                severity="non_blocking",
            )
        )
        actions.append(
            {
                "id": "record_wrapper_usage",
                "kind": "evidence_gap",
                "priority": 30,
                "label": "Record a wrapper-visible OMH workflow run",
                "why": "OMH can prepare chat-first workflows, but no wrapper/session artifact has been observed in this OMH home yet.",
                "operator_instruction": "Ask Hermes to use an OMH workflow, then let the wrapper record the route/session status.",
                "boundary": "A wrapper route/session record is chat orchestration evidence; it is not executor implementation evidence.",
                "capabilities": ["wrapper_metadata"],
            }
        )

    mcp_preference_status = _status(capabilities, "mcp_preference")
    if mcp_preference_status in {"unverified", "available"}:
        for name in ("mcp_bridge_runtime", "mcp_host_session"):
            if _status(capabilities, name) != "available":
                evidence_gaps.append(_gap_item(capabilities, name, category="evidence_gap", severity="non_blocking"))
        if _status(capabilities, "mcp_bridge_runtime") != "available" or _status(capabilities, "mcp_host_session") != "available":
            actions.append(
                {
                    "id": "verify_mcp_bridge",
                    "kind": "evidence_gap",
                    "priority": 40,
                    "label": "Verify the optional MCP bridge in the host",
                    "why": "The MCP bridge was requested or configured, but host load/session evidence is not complete.",
                    "command": "omh setup --with-mcp --mcp-host <host> && omh mcp sessions",
                    "boundary": "MCP config or bridge availability is not connector invocation, coding dispatch, review, CI, or merge evidence.",
                    "capabilities": ["mcp_bridge_runtime", "mcp_host_session"],
                }
            )

    optional_unknowns = [
        _gap_item(capabilities, name, category="host_unknown", severity="informational")
        for name in OPTIONAL_HOST_CAPABILITIES
        if _status(capabilities, name) in {"unknown", "unverified"}
    ]
    optional_unknowns = [item for item in optional_unknowns if item]
    if mcp_preference_status == "unknown":
        actions.append(
            {
                "id": "optional_mcp_setup",
                "kind": "optional_surface",
                "priority": 70,
                "label": "Optionally configure OMH as an MCP bridge",
                "why": "Normal Hermes chat workflows do not require MCP, but MCP-capable hosts can use it for local OMH status/recommend/probe tools.",
                "command": "omh setup --with-mcp --mcp-host <host>",
                "boundary": "MCP setup can write supported host config entries; host load/use still needs observed host evidence.",
                "capabilities": ["mcp_preference", "mcp_host_config"],
            }
        )

    baseline_gaps.extend(plugin_smoke_gaps)

    actions.sort(key=_action_priority)
    product_gap_count = len({str(item["capability"]) for item in baseline_gaps if item})
    evidence_gap_count = len({str(item["capability"]) for item in evidence_gaps if item})
    optional_count = len({str(item["capability"]) for item in optional_unknowns if item})

    return {
        "schema_version": CAPABILITY_GAP_ROADMAP_SCHEMA_VERSION,
        "summary": {
            "baseline_product_gaps": product_gap_count,
            "evidence_gaps": evidence_gap_count,
            "optional_or_host_unknowns": optional_count,
            "baseline_ready": product_gap_count == 0,
            "native_runtime_observed": bool(probe_payload.get("plugin_runtime_active")),
            "wrapper_usage_observed": _status(capabilities, "wrapper_metadata") == "available",
        },
        "product_gaps": baseline_gaps,
        "evidence_gaps": [item for item in evidence_gaps if item],
        "optional_or_host_unknowns": optional_unknowns,
        "next_actions": actions,
        "claim_boundary": (
            "This roadmap separates missing OMH product setup from missing host/runtime evidence. "
            "It does not turn unknown or unverified host surfaces into product defects, and it does not "
            "claim plugin load, MCP host use, wrapper routing, executor work, review, CI, or merge without matching observations."
        ),
    }


def _capability_map(probe_payload: dict[str, object]) -> dict[str, dict[str, object]]:
    capabilities = probe_payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        return {}
    return {
        str(capability.get("name", "")): capability
        for capability in capabilities
        if isinstance(capability, dict) and str(capability.get("name", "")).strip()
    }


def _status(capabilities: dict[str, dict[str, object]], name: str) -> str:
    capability = capabilities.get(name)
    if not capability:
        return "unknown"
    return str(capability.get("status", "unknown"))


def _gap_item(
    capabilities: dict[str, dict[str, object]],
    name: str,
    *,
    category: str,
    severity: str,
) -> dict[str, object]:
    capability = capabilities.get(name, {})
    return {
        "capability": name,
        "category": category,
        "severity": severity,
        "status": str(capability.get("status", "unknown")),
        "message": str(capability.get("message", "")),
        "evidence": str(capability.get("evidence", "")),
    }


def _action_priority(item: dict[str, object]) -> int:
    priority = item.get("priority", 100)
    if isinstance(priority, int):
        return priority
    if isinstance(priority, str) and priority.isdigit():
        return int(priority)
    return 100
