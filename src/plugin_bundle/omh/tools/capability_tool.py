from __future__ import annotations

import json

from ..awareness import awareness_lane_examples, awareness_primer_payload
from ..metadata import PROVIDED_HOOKS, PROVIDED_TOOLS

STANDALONE_CAPABILITY_SECTIONS = (
    "omh_awareness",
    "agent_roles",
    "skills",
    "hooks",
    "keywords",
    "orchestration_patterns",
    "tool_requirements",
    "evidence_boundaries",
)
CONCEPTUAL_AWARENESS_SURFACES = {
    "request-to-handoff",
    "executor selection",
    "coding runtime handoff",
}
LANE_OWNER_ROLES = {
    "intent_to_plan": "planner",
    "research_and_ops": "researcher",
    "materials_and_visuals": "operator",
    "automation_and_status": "tracker",
    "coding_handoff": "handoff-guide",
}


def standalone_skill_capability_ids() -> set[str]:
    """Return degraded plugin fallback skill ids for release/package smoke checks."""
    return {str(item["id"]) for item in _standalone_skill_capabilities()}


def standalone_skill_capability_items() -> list[dict[str, object]]:
    """Return degraded plugin fallback skill capabilities for release/package smoke checks."""
    return _standalone_skill_capabilities()


OMH_CAPABILITIES_SCHEMA = {
    "name": "omh_capabilities",
    "description": (
        "Read OMH agent, skill, hook, keyword, orchestration, tool, and evidence capability manifests. "
        "Capability presence is metadata only, not observed execution evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["export", "list", "inspect"],
                "description": "Capability action to perform.",
            },
            "section": {
                "type": "string",
                "description": "Optional capability section filter.",
            },
            "id": {
                "type": "string",
                "description": "Capability id for action=inspect.",
            },
        },
    },
}


def omh_capabilities_handler(args: dict, **kwargs) -> str:
    action = str(args.get("action", "export") or "export")
    section = str(args.get("section", "") or "") or None
    try:
        payload = _handle_capability_action(action, section, str(args.get("id", "") or ""))
    except ValueError as exc:
        payload = {"error": str(exc)}
    return json.dumps(payload, sort_keys=True)


def _handle_capability_action(action: str, section: str | None, capability_id: str) -> dict[str, object]:
    registry = _load_package_registry()
    if registry:
        if action == "export":
            return registry["filtered_capability_snapshot"](section)
        if action == "list":
            return registry["list_capabilities"](section)
        if action == "inspect":
            return registry["inspect_capability"](capability_id, section=section)
        return {"error": f"unknown action: {action}"}
    if action == "export":
        return _standalone_capability_snapshot(section)
    if action == "list":
        return _standalone_capability_list(section)
    if action == "inspect":
        return _standalone_capability_inspect(capability_id, section)
    return {"error": f"unknown action: {action}"}


def _load_package_registry() -> dict[str, object]:
    try:
        from omh.capabilities.registry import filtered_capability_snapshot, inspect_capability, list_capabilities
    except ModuleNotFoundError:
        return {}
    return {
        "filtered_capability_snapshot": filtered_capability_snapshot,
        "inspect_capability": inspect_capability,
        "list_capabilities": list_capabilities,
    }


def _standalone_capability_snapshot(section: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "omh_capability_manifest/v1",
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "determinism": "static_plugin_metadata_no_runtime_clock",
        "summary": {name: len(value) if isinstance(value, list) else len(value.keys()) for name, value in _standalone_sections().items()},
        "evidence_boundaries": _standalone_evidence_boundaries(),
        "non_goals": [
            "standalone plugin fallback does not expose the full installed skill catalog",
            "capability presence is not Hermes plugin load, execution, review, CI, or merge evidence",
        ],
    }
    sections = _standalone_sections()
    if section:
        if section not in sections:
            raise ValueError(f"unknown capability section: {section}")
        payload["section"] = section
        payload[section] = sections[section]
        return payload
    payload.update(sections)
    return payload


def _standalone_capability_list(section: str | None = None) -> dict[str, object]:
    sections = _standalone_sections()
    if section:
        if section not in sections:
            raise ValueError(f"unknown capability section: {section}")
        return {
            "schema_version": "omh_capability_list/v1",
            "section": section,
            "ids": _standalone_ids(sections[section]),
            "degraded": True,
        }
    return {
        "schema_version": "omh_capability_list/v1",
        "sections": [
            {"section": name, "ids": _standalone_ids(value)}
            for name, value in sorted(sections.items())
        ],
        "degraded": True,
    }


def _standalone_capability_inspect(capability_id: str, section: str | None = None) -> dict[str, object]:
    wanted = str(capability_id or "").strip()
    if not wanted:
        raise ValueError("capabilities inspect requires an id")
    sections = _standalone_sections()
    if section and section not in sections:
        raise ValueError(f"unknown capability section: {section}")
    search = {section: sections[section]} if section else sections
    for section_name, values in search.items():
        for item in _standalone_items(values):
            if _standalone_matches(wanted, item):
                return {
                    "schema_version": "omh_capability_inspect/v1",
                    "section": section_name,
                    "id": wanted,
                    "requested_id": wanted,
                    "resolved_id": _standalone_item_id(item, wanted),
                    "capability": item,
                    "degraded": True,
                }
        if isinstance(values, dict) and wanted in values:
            return {
                "schema_version": "omh_capability_inspect/v1",
                "section": section_name,
                "id": wanted,
                "requested_id": wanted,
                "resolved_id": wanted,
                "capability": values[wanted],
                "degraded": True,
            }
    raise ValueError(f"unknown capability id: {wanted}")


def _standalone_sections() -> dict[str, object]:
    return {
        "omh_awareness": awareness_primer_payload(),
        "agent_roles": [
            {
                "schema_version": "agent_role_capability/v1",
                "id": "guide",
                "display_name": "Guide",
                "legacy_ids": ["hybrid-guidance", "retained-router"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["plain request routing", "workflow recommendation"],
                "does_not_own": ["plan acceptance", "dispatch", "execution", "review", "CI", "merge"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "researcher",
                "display_name": "Researcher",
                "legacy_ids": ["research-lead"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["source-backed research guidance"],
                "does_not_own": ["implementation evidence", "review", "CI", "merge"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "planner",
                "display_name": "Planner",
                "legacy_ids": ["planning-lead"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["plan shaping", "acceptance criteria", "verification strategy"],
                "does_not_own": ["executor dispatch", "implementation evidence"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "operator",
                "display_name": "Operator",
                "legacy_ids": ["retained-operator"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["business and product workflow guidance", "materials and operations cards"],
                "does_not_own": ["external delivery", "file export", "deploy", "platform evidence"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "memory-keeper",
                "display_name": "Memory Keeper",
                "legacy_ids": ["retained-knowledge"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["memory and wiki context review"],
                "does_not_own": ["unobserved memory mutation"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "handoff-guide",
                "display_name": "Handoff Guide",
                "legacy_ids": ["coding-handoff", "runtime-handoff-guidance", "codex-handoff-guidance"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["executor-neutral handoff guidance", "prepared-vs-observed status narration"],
                "does_not_own": ["hidden coding execution", "review", "CI", "merge"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "tracker",
                "display_name": "Tracker",
                "legacy_ids": ["hybrid-measurement"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["runtime status", "tool readiness", "observability narration"],
                "does_not_own": ["unobserved runtime or platform action"],
            },
            {
                "schema_version": "agent_role_capability/v1",
                "id": "reviewer",
                "display_name": "Reviewer",
                "legacy_ids": ["review-gate", "hybrid-review", "hybrid-verification"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["review evidence interpretation"],
                "does_not_own": ["unobserved review claims"],
            },
        ],
        "skills": _standalone_skill_capabilities(),
        "hooks": {
            "schema_version": "omh_hook_manifest/v1",
            "plugin_tools": [
                {
                    "name": name,
                    "supported_by_plugin_bundle": True,
                    "supported_by_wrapper_contract": name in {"omh_status", "omh_hud", "omh_capabilities"},
                    "supported_by_cli_backend": name == "omh_capabilities",
                    "observed_in_this_environment": False,
                }
                for name in PROVIDED_TOOLS
            ],
            "plugin_hooks": [
                {
                    "name": name,
                    "supported_by_plugin_bundle": True,
                    "payload_fields": _standalone_hook_payload_fields(name),
                    "claim_boundary": "Hook availability is not proof that Hermes loaded or invoked the plugin.",
                    "observed_in_this_environment": False,
                }
                for name in PROVIDED_HOOKS
            ],
        },
        "keywords": {
            "schema_version": "keyword_detector_manifest/v1",
            "explicit_invocation_prefixes": [
                {"prefix": "$", "strength": "exact", "precedence": 1},
                {"prefix": "/", "strength": "exact", "precedence": 1},
                {"prefix": "./", "strength": "exact", "precedence": 1},
                {"prefix": "@", "strength": "exact", "precedence": 1},
            ],
            "guard_policy_catalog": [
                {
                    "id": "risky_refactor_before_cleanup",
                    "rule": "Risky refactor language should route to planning/review before cleanup unless explicit invocation overrides.",
                    "activation_status": "active",
                },
                {
                    "id": "feedback_before_coding",
                    "rule": "Product feedback and bug reports should route through triage/investigation before coding handoff unless code work is explicit.",
                    "activation_status": "cataloged",
                },
            ],
            "degraded": True,
        },
        "orchestration_patterns": [
            {
                "schema_version": "orchestration_pattern/v1",
                "id": "executor_session_handoff",
                "owner_role": "handoff-guide",
                "observed_evidence_required": [
                    "handoff_prepared",
                    "dispatch_observed",
                    "result_observed",
                    "verification_observed",
                ],
                "prepared_is_not": _standalone_evidence_boundaries()["prepared_is_not"],
            },
            {
                "schema_version": "orchestration_pattern/v1",
                "id": "plan_execute_verify",
                "owner_role": "planner",
                "observed_evidence_required": ["plan_accepted", "execution_observed", "verification_observed"],
                "prepared_is_not": _standalone_evidence_boundaries()["prepared_is_not"],
            },
        ],
        "tool_requirements": _standalone_tool_requirements(),
        "evidence_boundaries": _standalone_evidence_boundaries(),
    }


def _standalone_matches(wanted: str, item: dict[str, object]) -> bool:
    aliases = item.get("legacy_ids", ())
    legacy_ids = aliases if isinstance(aliases, list) else ()
    values = {
        str(item.get("id") or ""),
        str(item.get("name") or ""),
        str(item.get("skill") or ""),
        *[str(alias) for alias in legacy_ids],
    }
    return wanted in values


def _standalone_hook_payload_fields(name: str) -> list[str]:
    if name == "pre_llm_call":
        return ["omh_awareness_primer", "bounded_status_context", "redacted"]
    if name == "pre_tool_call":
        return ["tool_name", "claim_boundary"]
    if name == "on_session_end":
        return ["session_summary", "metadata_only"]
    return []


def _standalone_item_id(item: dict[str, object], fallback: str) -> str:
    return str(item.get("id") or item.get("name") or item.get("skill") or fallback)


def _standalone_skill_capabilities() -> list[dict[str, object]]:
    capabilities: list[dict[str, object]] = []
    seen: set[str] = set()
    awareness = awareness_primer_payload()
    chat_rule = str(awareness.get("chat_rule") or "")
    context_rule = str(awareness.get("all_skill_context_rule") or "")
    evidence_boundary = str(awareness.get("evidence_boundary") or "")
    fallback_rule = str(awareness.get("fallback_rule") or "")
    for lane in awareness["lanes"]:
        if not isinstance(lane, dict):
            continue
        lane_id = str(lane.get("id") or "")
        lane_label = str(lane.get("label") or lane_id)
        owner_role = LANE_OWNER_ROLES.get(lane_id, "guide")
        skills = lane.get("skills", [])
        if not isinstance(skills, list):
            continue
        for skill in skills:
            skill_id = str(skill)
            if skill_id in seen or skill_id in CONCEPTUAL_AWARENESS_SURFACES:
                continue
            seen.add(skill_id)
            capabilities.append(
                {
                    "schema_version": "skill_capability/v1",
                    "id": skill_id,
                    "display_name": skill_id.replace("-", " ").title(),
                    "runtime_claim": "skill_guidance_not_execution",
                    "primary_owner_role": owner_role,
                    "awareness_lane": lane_id,
                    "awareness_lane_label": lane_label,
                    "use_for": str(lane.get("use_for") or ""),
                    "workflow_routing_hint": (
                        f"Use `{skill_id}` when the request fits {lane_label}: "
                        f"{lane.get('use_for') or 'OMH workflow guidance'}. "
                        "If the request crosses lanes, name the adjacent OMH workflow first."
                    ),
                    "workflow_context_rule": context_rule,
                    "chat_rule": chat_rule,
                    "fallback_rule": fallback_rule,
                    "evidence_boundary": evidence_boundary,
                    "cross_lane_examples": awareness_lane_examples(lane_id),
                    "degraded": True,
                }
            )
    return sorted(capabilities, key=lambda item: str(item["id"]))


def _standalone_tool_requirements() -> dict[str, object]:
    return {
        "schema_version": "tool_requirement_manifest/v1",
        "derivation_status": "degraded_partial",
        "items": [
            {
                "skill": item["id"],
                "derivation_status": "degraded_partial",
                "required_tools": [],
                "required_mcps": [],
                "fallback": "Standalone plugin fallback cannot inspect the installed skill catalog; use Hermes-native guidance or selected executor handoff.",
                "source_refs": ["src/plugin_bundle/omh/tools/capability_tool.py"],
            }
            for item in _standalone_skill_capabilities()
        ],
        "claim_boundary": "Tool requirements are advisory until a host/plugin/wrapper reports observed tool availability.",
    }


def _standalone_evidence_boundaries() -> dict[str, str]:
    return {
        "prepared_is_not": (
            "Prepared OMH capability, handoff, topology, or routing metadata is not execution, worker dispatch, "
            "worktree creation, review, CI, merge-readiness, or merge evidence."
        ),
        "observed_required_for": "Runtime status changes require recorded wrapper/runtime/plugin evidence.",
        "claim_rule": "Standalone plugin metadata is a capability hint, not proof of host invocation.",
    }


def _standalone_ids(value: object) -> list[str]:
    if isinstance(value, dict) and not _standalone_items(value):
        return sorted(str(key) for key in value)
    return sorted(str(item.get("id") or item.get("name") or item.get("skill")) for item in _standalone_items(value))


def _standalone_items(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        items = []
        for key in ("plugin_tools", "plugin_hooks", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                items.extend(item for item in nested if isinstance(item, dict))
        if not items and "schema_version" in value:
            items.append(value)
        return items
    return []
