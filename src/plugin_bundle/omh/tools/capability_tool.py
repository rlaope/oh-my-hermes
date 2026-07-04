from __future__ import annotations

import json

from ..awareness import awareness_lane_examples, awareness_primer_payload
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..metadata import PROVIDED_HOOKS, PROVIDED_TOOLS

STANDALONE_CAPABILITY_SECTIONS = (
    "omh_awareness",
    "agent_roles",
    "skills",
    "hooks",
    "keywords",
    "orchestration_patterns",
    "playbooks",
    "tool_requirements",
    "evidence_boundaries",
)
STANDALONE_CAPABILITY_SECTION_ALIASES = {
    "awareness": "omh_awareness",
    "agent": "agent_roles",
    "agents": "agent_roles",
    "role": "agent_roles",
    "roles": "agent_roles",
    "hook": "hooks",
    "keyword": "keywords",
    "pattern": "orchestration_patterns",
    "patterns": "orchestration_patterns",
    "orchestration": "orchestration_patterns",
    "playbook": "playbooks",
    "tool": "tool_requirements",
    "tools": "tool_requirements",
    "tooling": "tool_requirements",
    "boundary": "evidence_boundaries",
    "boundaries": "evidence_boundaries",
    "evidence": "evidence_boundaries",
}
CONCEPTUAL_AWARENESS_SURFACES = {
    "request-to-handoff",
    "executor selection",
    "coding runtime handoff",
}
LANE_OWNER_ROLES = {
    "intent_to_plan": "planner",
    "research_and_ops": "researcher",
    "retained_knowledge": "memory-keeper",
    "materials_and_visuals": "operator",
    "automation_and_status": "tracker",
    "coding_handoff": "handoff-guide",
}
STANDALONE_CAPABILITY_FAMILIES = (
    {
        "id": "plan_and_decide",
        "label": "Plan and decide",
        "owner_role": "planner",
        "source_lanes": ("intent_to_plan",),
        "use_for": "Ambiguous goals, planning, decisions, and loopable work before execution.",
        "primary_workflows": (
            "deep-interview",
            "ralplan",
            "codebase-onboarding",
            "codegraph-refresh",
            "ultragoal",
            "loop",
            "strategy-brief",
            "oh-my-hermes",
            "plan",
            "ralph",
            "performance-goal",
        ),
        "next_action": "clarify_or_prepare_plan",
        "example_prompt": "Make onboarding feel smoother.",
        "route_summary": "Clarify the goal, choose the planning depth, and show the next concrete action.",
        "not_evidence_until_observed": ("plan acceptance", "executor dispatch", "verification"),
    },
    {
        "id": "learn_and_gather",
        "label": "Learn and gather",
        "owner_role": "researcher",
        "source_lanes": ("research_and_ops",),
        "use_for": "Source finding, web research, papers, customer signals, and briefings.",
        "primary_workflows": (
            "source-finder",
            "web-research",
            "paper-learning",
            "research-department",
            "feedback-triage",
            "best-practice-research",
            "autoresearch-goal",
            "research-brief",
            "meeting-brief",
        ),
        "next_action": "gather_source_backed_evidence",
        "example_prompt": "Find papers, datasets, and repos for this topic.",
        "route_summary": "Name the source/synthesis split before summarizing or planning from the material.",
        "not_evidence_until_observed": ("source retrieval", "source verification", "decision approval"),
    },
    {
        "id": "retain_knowledge",
        "label": "Retain knowledge",
        "owner_role": "memory-keeper",
        "source_lanes": ("retained_knowledge",),
        "use_for": "Project wiki notes and external connection hints.",
        "primary_workflows": ("wiki",),
        "next_action": "prepare_retained_knowledge_guidance",
        "example_prompt": "Capture this decision.",
        "route_summary": "Prepare notes and hints without claiming writes.",
        "not_evidence_until_observed": ("external write", "memory mutation", "connector I/O", "source verification"),
    },
    {
        "id": "create_materials_and_visuals",
        "label": "Create materials and visuals",
        "owner_role": "operator",
        "source_lanes": ("materials_and_visuals",),
        "use_for": "Decks, PDFs, spreadsheets, reports, websites, frontend surfaces, accessibility audits, posters, image cards, visual QA, and shareable packages.",
        "primary_workflows": (
            "design-quality-gate",
            "frontend",
            "accessibility-audit",
            "visual-qa",
            "materials-package",
            "report-package",
            "deliverable-package",
            "img-summary",
        ),
        "next_action": "prepare_material_or_visual_card",
        "example_prompt": "Make a PR summary card for reviewers.",
        "route_summary": "Prepare the copy, prompt, package, or QA contract before claiming generated output.",
        "not_evidence_until_observed": ("frontend implementation", "accessibility PASS", "file export", "image generation", "visual QA", "delivery"),
    },
    {
        "id": "delegate_coding_and_ship",
        "label": "Delegate coding and ship",
        "owner_role": "handoff-guide",
        "source_lanes": ("coding_handoff",),
        "use_for": "Scoped coding handoffs, executor choice, review, QA, CI, and merge readiness.",
        "primary_workflows": (
            "idea-to-deploy",
            "ultraprocess",
            "code-review",
            "verification-gate",
            "security-safety-review",
            "team",
            "ultrawork",
            "ultraqa",
            "cto-loop",
            "deploy-and-monitor",
            "ai-slop-cleaner",
            "request-to-handoff",
            "executor selection",
            "coding runtime handoff",
        ),
        "executor_choices": ("Codex", "Claude Code", "Hermes", "generic runtime"),
        "next_action": "prepare_scoped_coding_handoff",
        "example_prompt": "Turn this issue into a PR-ready plan and hand it to implementation.",
        "route_summary": "Choose the coding owner only after scope is concrete, then track observed evidence separately.",
        "not_evidence_until_observed": ("executor dispatch", "implementation", "review", "CI", "merge"),
    },
    {
        "id": "operate_and_observe",
        "label": "Operate and observe",
        "owner_role": "tracker",
        "source_lanes": ("automation_and_status",),
        "use_for": "Setup repair, status, automation, workflow learning, memory review, and ops cards.",
        "primary_workflows": (
            "doctor",
            "workspace-audit",
            "production-audit",
            "automation-blueprint",
            "agent-ops-review",
            "agent-debug",
            "failure-signal-audit",
            "instinct-ledger",
            "agent-evaluation",
            "rules-distill",
            "context-budget-review",
            "skill-scout",
            "skill-health",
            "workflow-learning",
            "memory-curation-review",
            "achievements",
            "harness-session-inventory",
            "ops-observability-card",
            "skill",
            "ask",
            "cancel",
        ),
        "next_action": "show_status_or_prepare_operating_card",
        "example_prompt": "Why did this route to plan? Make it a regression.",
        "route_summary": "Show status, repair, schedule, or learning shape without claiming runtime actions happened.",
        "not_evidence_until_observed": ("schedule creation", "connector I/O", "runtime load", "skill patch approval"),
    },
)
STANDALONE_LANE_PLAYBOOK_IDS = {
    "intent_to_plan": ("request-to-handoff", "safe-feature-change"),
    "research_and_ops": ("source-finder", "research-department", "source-backed-research", "feedback-triage"),
    "retained_knowledge": (),
    "materials_and_visuals": ("materials-processing",),
    "automation_and_status": ("scheduled-ops-blueprint",),
    "coding_handoff": ("idea-to-deploy",),
}


def standalone_skill_capability_ids() -> set[str]:
    """Return degraded plugin fallback skill ids for release/package smoke checks."""
    return {str(item["id"]) for item in _standalone_skill_capabilities()}


def standalone_skill_capability_items() -> list[dict[str, object]]:
    """Return degraded plugin fallback skill capabilities for release/package smoke checks."""
    return _standalone_skill_capabilities()


def standalone_playbook_capability_items() -> list[dict[str, object]]:
    """Return degraded plugin fallback playbook capabilities for release/package smoke checks."""
    return _standalone_playbook_capabilities()


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
                "enum": ["summary", "export", "list", "inspect"],
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
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_capabilities_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_capabilities", args, kwargs)
    action = str(args.get("action", "export") or "export")
    section = str(args.get("section", "") or "") or None
    try:
        payload = _handle_capability_action(action, section, str(args.get("id", "") or ""))
    except ValueError as exc:
        payload = {"error": str(exc)}
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _handle_capability_action(action: str, section: str | None, capability_id: str) -> dict[str, object]:
    registry = _load_package_registry()
    if registry:
        if action == "summary":
            return registry["capability_summary"]()
        if action == "export":
            return registry["filtered_capability_snapshot"](section)
        if action == "list":
            return registry["list_capabilities"](section)
        if action == "inspect":
            return registry["inspect_capability"](capability_id, section=section)
        return {"error": f"unknown action: {action}"}
    if action == "summary":
        return _standalone_capability_summary()
    if action == "export":
        return _standalone_capability_snapshot(section)
    if action == "list":
        return _standalone_capability_list(section)
    if action == "inspect":
        return _standalone_capability_inspect(capability_id, section)
    return {"error": f"unknown action: {action}"}


def _load_package_registry() -> dict[str, object]:
    try:
        from omh.capabilities.registry import capability_summary, filtered_capability_snapshot, inspect_capability, list_capabilities
    except ImportError:
        return {}
    return {
        "capability_summary": capability_summary,
        "filtered_capability_snapshot": filtered_capability_snapshot,
        "inspect_capability": inspect_capability,
        "list_capabilities": list_capabilities,
    }


def _standalone_capability_summary() -> dict[str, object]:
    awareness = awareness_primer_payload()
    sections = _standalone_sections()
    skills = {str(item.get("id")): item for item in _standalone_items(sections["skills"])}
    playbooks = {str(item.get("id")): item for item in _standalone_items(sections["playbooks"])}
    lanes = [
        _standalone_summary_lane(lane, skills, playbooks)
        for lane in awareness.get("lanes", [])
        if isinstance(lane, dict)
    ]
    return {
        "schema_version": "omh_capability_summary/v1",
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "determinism": "static_plugin_metadata_no_runtime_clock",
        "purpose": (
            "Compact Hermes-facing summary for answering what OMH can do, choosing the nearest workflow, "
            "and rendering a picker/card without requiring shell catalog approval."
        ),
        "chat_rule": str(awareness.get("chat_rule") or ""),
        "totals": {
            "skills": len(skills),
            "playbooks": len(playbooks),
            "agent_roles": len(_standalone_items(sections["agent_roles"])),
            "capability_families": len(STANDALONE_CAPABILITY_FAMILIES),
        },
        "capability_families": _standalone_capability_families(),
        "workflow_to_family": _standalone_workflow_to_family(),
        "lanes": lanes,
        "workflow_context_cards": awareness.get("workflow_context_cards", []),
        "direct_response_guidance": [
            "When a user asks what OMH can do, summarize capability families and offer the workflow picker.",
            "When a request matches a family, name the likely workflow and the first safe next action.",
            "When a request crosses families, name the adjacent workflow before preparing handoff or status.",
            "Use friendly section aliases for input, but keep canonical names in machine-readable output.",
        ],
        "section_aliases": dict(sorted(STANDALONE_CAPABILITY_SECTION_ALIASES.items())),
        "evidence_boundary": _standalone_evidence_boundaries()["prepared_is_not"],
    }


def _standalone_summary_lane(
    lane: dict[str, object],
    skills: dict[str, dict[str, object]],
    playbooks: dict[str, dict[str, object]],
) -> dict[str, object]:
    lane_id = str(lane.get("id") or "")
    lane_skills = lane.get("skills", [])
    if not isinstance(lane_skills, list):
        lane_skills = []
    representative_playbooks = [
        _standalone_compact_playbook(playbooks[playbook_id])
        for playbook_id in STANDALONE_LANE_PLAYBOOK_IDS.get(lane_id, ())
        if playbook_id in playbooks
    ]
    return {
        "id": lane_id,
        "label": str(lane.get("label") or lane_id),
        "owner_role": LANE_OWNER_ROLES.get(lane_id, "guide"),
        "use_for": str(lane.get("use_for") or ""),
        "primary_skills": [str(skill) for skill in lane_skills if str(skill) in skills],
        "representative_playbooks": representative_playbooks,
        "wrapper_actions": sorted(
            {
                str(action)
                for playbook in representative_playbooks
                for action in playbook.get("available_wrapper_actions", [])
            }
        )[:8],
        "examples": awareness_lane_examples(lane_id),
    }


def standalone_capability_family_cards() -> list[dict[str, object]]:
    return _standalone_capability_families()


def _standalone_capability_families() -> list[dict[str, object]]:
    families: list[dict[str, object]] = []
    for family in STANDALONE_CAPABILITY_FAMILIES:
        source_lanes = [str(lane) for lane in family.get("source_lanes", ()) if str(lane)]
        payload = {
            **family,
            "source_lanes": source_lanes,
            "primary_workflows": list(family.get("primary_workflows", ())),
            "not_evidence_until_observed": list(family.get("not_evidence_until_observed", ())),
            "source_examples": [
                example
                for lane_id in source_lanes
                for example in awareness_lane_examples(lane_id)
            ][:4],
        }
        if family.get("executor_choices"):
            payload["executor_choices"] = list(family.get("executor_choices", ()))
        families.append(payload)
    return families


def _standalone_workflow_to_family() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for family in STANDALONE_CAPABILITY_FAMILIES:
        family_id = str(family.get("id", ""))
        for workflow in family.get("primary_workflows", ()):
            text = str(workflow)
            if text and family_id:
                mapping[text] = family_id
                mapping[text.casefold()] = family_id
    for lane in awareness_primer_payload().get("lanes", []):
        if not isinstance(lane, dict):
            continue
        family_id = _standalone_default_family_for_source_lane(str(lane.get("id", "")))
        if not family_id:
            continue
        for workflow in lane.get("skills", []):
            text = str(workflow)
            if text:
                mapping.setdefault(text, family_id)
                mapping.setdefault(text.casefold(), family_id)
    return dict(sorted(mapping.items()))


def _standalone_default_family_for_source_lane(lane_id: str) -> str:
    for family in STANDALONE_CAPABILITY_FAMILIES:
        if lane_id in family.get("source_lanes", ()):
            return str(family.get("id", ""))
    return ""


def _standalone_compact_playbook(playbook: dict[str, object]) -> dict[str, object]:
    first_stage = playbook.get("first_stage")
    return {
        "id": str(playbook.get("id") or ""),
        "display_name": str(playbook.get("display_name") or playbook.get("id") or ""),
        "summary": str(playbook.get("summary") or ""),
        "owner_role": str(playbook.get("primary_owner_role") or "guide"),
        "first_stage": first_stage if isinstance(first_stage, dict) else {},
        "available_wrapper_actions": [
            str(action)
            for action in playbook.get("available_wrapper_actions", [])
            if str(action)
        ][:8],
    }


def _standalone_capability_snapshot(section: str | None = None) -> dict[str, object]:
    canonical_section = _standalone_normalize_section(section)
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
    if canonical_section:
        if canonical_section not in sections:
            raise ValueError(f"unknown capability section: {section}")
        payload["section"] = canonical_section
        payload[canonical_section] = sections[canonical_section]
        return payload
    payload.update(sections)
    return payload


def _standalone_capability_list(section: str | None = None) -> dict[str, object]:
    canonical_section = _standalone_normalize_section(section)
    sections = _standalone_sections()
    if canonical_section:
        if canonical_section not in sections:
            raise ValueError(f"unknown capability section: {section}")
        return {
            "schema_version": "omh_capability_list/v1",
            "section": canonical_section,
            "ids": _standalone_ids(sections[canonical_section]),
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
    canonical_section = _standalone_normalize_section(section)
    sections = _standalone_sections()
    if canonical_section and canonical_section not in sections:
        raise ValueError(f"unknown capability section: {section}")
    search = {canonical_section: sections[canonical_section]} if canonical_section else sections
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


def _standalone_normalize_section(section: str | None) -> str | None:
    if not section:
        return None
    normalized = section.strip()
    return STANDALONE_CAPABILITY_SECTION_ALIASES.get(normalized, normalized)


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
                "id": "builder",
                "display_name": "Builder",
                "legacy_ids": ["implementation-owner"],
                "runtime_claim": "descriptor_not_runtime_agent",
                "owns": ["prepared playbook implementation step", "selected executor/runtime ownership narration"],
                "does_not_own": ["hidden runtime execution", "unobserved worker dispatch", "review", "CI", "merge"],
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
        "playbooks": _standalone_playbook_capabilities(),
        "tool_requirements": _standalone_tool_requirements(),
        "achievement_evidence": _standalone_achievement_evidence(),
        "evidence_boundaries": _standalone_evidence_boundaries(),
    }


def _standalone_achievement_evidence() -> list[dict[str, object]]:
    # Mirrors src/capabilities/achievements.py because the plugin bundle stays standalone.
    return [
        {
            "schema_version": "achievement_evidence_contract/v1",
            "id": "hermes_achievements_observation",
            "display_name": "Hermes achievements observation",
            "source": (
                "Local hermes-achievements plugin artifacts: scan_snapshot.json, state.json, "
                "and agent_summary.json when the upstream plugin writes it."
            ),
            "claim_kind": "observed_badge_metadata",
            "claim_fields": [
                "badge_id",
                "name",
                "tier",
                "category",
                "state",
                "progress_percent",
                "unlocked_at",
            ],
            "profile_fields": [
                "strengths",
                "gaps",
                "top_tier",
                "unlocked_count",
                "total_count",
                "derivation",
            ],
            "evidence_rule": (
                "A badge or profile field may be claimed only when it was read from local hermes-achievements "
                "plugin artifacts; OMH never rescans Hermes session history and never recomputes unlocks."
            ),
            "degradation_rule": (
                "Missing, corrupt, or unknown-shaped artifacts degrade to a not_observed report instead of "
                "failing or guessing."
            ),
            "not_evidence_for": [
                "productivity",
                "code_quality",
                "execution",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
            "surfaces": [
                "omh achievements",
                "hud full preset",
                "context brief achievements_profile",
                "achievements skill",
            ],
            "degraded": True,
        }
    ]


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
        return ["omh_awareness_primer", "omh_context_brief", "omh_route_hint", "bounded_status_context", "redacted"]
    if name == "pre_tool_call":
        return ["tool_name", "tool_family_hint", "omh_generic_tool_checkpoint", "claim_boundary", "redacted"]
    if name == "on_session_end":
        return ["session_summary", "metadata_only"]
    return []


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


def _standalone_item_id(item: dict[str, object], fallback: str) -> str:
    return str(item.get("id") or item.get("name") or item.get("skill") or fallback)


def _standalone_skill_capabilities() -> list[dict[str, object]]:
    capabilities: list[dict[str, object]] = []
    seen: set[str] = set()
    awareness = awareness_primer_payload()
    chat_rule = str(awareness.get("chat_rule") or "")
    context_rule = str(awareness.get("all_skill_context_rule") or "")
    evidence_boundary = (
        "Prepared OMH guidance is not observed execution, delivery, review, CI, merge-readiness, or merge evidence."
    )
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
                        f"Use `{skill_id}` for {lane_label}: {lane.get('use_for') or 'OMH workflow guidance'}; "
                        "name adjacent workflow."
                    ),
                    "workflow_context_rule": context_rule,
                    "chat_rule": chat_rule,
                    "fallback_rule": fallback_rule,
                    "evidence_boundary": evidence_boundary,
                    "cross_lane_examples": _standalone_skill_lane_examples(lane_id, skill_id),
                    "degraded": True,
                }
            )
    return sorted(capabilities, key=lambda item: str(item["id"]))


def _standalone_skill_lane_examples(lane_id: str, skill_id: str) -> list[str]:
    examples = awareness_lane_examples(lane_id)
    return examples[:1]


def _standalone_playbook_capabilities() -> list[dict[str, object]]:
    awareness = awareness_primer_payload()
    chat_rule = str(awareness.get("chat_rule") or "")
    fallback_rule = str(awareness.get("fallback_rule") or "")
    evidence_boundary = str(awareness.get("evidence_boundary") or "")
    context_rule = (
        "Use OMH playbooks as situation-level workflow maps: choose the nearest playbook for the user's request, "
        "then route to the named skills, roles, harnesses, or wrapper actions without claiming hidden execution."
    )
    return [
        _standalone_playbook(
            "request-to-handoff",
            "Request to handoff",
            "Turn a plain Hermes request into a role-owned next action with an explicit evidence boundary.",
            (
                "Use when the user asks naturally and Hermes must decide whether to clarify, research, plan, "
                "review, or prepare a coding handoff."
            ),
            ("route_request", "select_role", "plan_or_prepare", "handoff_or_retain", "status_card"),
            "guide",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "safe-feature-change",
            "Safe feature change",
            "Shape a risky or meaningful feature request into scope, tests, review, and executor-ready work.",
            "Use when a repo change should be safer than direct implementation.",
            ("clarify_scope", "risk_plan", "prepare_executor_handoff", "verification_status"),
            "planner",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "source-backed-research",
            "Source-backed research",
            "Keep research requests grounded in sources, caveats, synthesis, and decision-ready output.",
            "Use when Hermes should research before recommending or planning.",
            ("question", "source_gathering", "synthesis", "brief", "status_card"),
            "researcher",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "source-finder",
            "Source finder",
            "Prepare typed source candidates, acquisition status, provenance, and downstream workflow choice.",
            "Use when Hermes should find or classify papers, links, datasets, repos, presentations, docs, or specs before downstream work.",
            ("source_scope", "candidate_set", "acquisition_status", "downstream_choice"),
            "researcher",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "feedback-triage",
            "Feedback triage",
            "Convert product feedback, bugs, and user signals into investigation, repro, priority, and next action.",
            "Use when customers report issues such as payment failures, confusing UX, or recurring bugs.",
            ("capture_signal", "triage", "investigation_plan", "handoff_or_record"),
            "operator",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "scheduled-ops-blueprint",
            "Scheduled ops blueprint",
            "Prepare recurring work as a schedule, delivery policy, silence rule, and status-card boundary.",
            "Use when the user asks Hermes to check something periodically or deliver recurring summaries.",
            ("scope_schedule", "select_sources", "delivery_policy", "confirmation_card"),
            "tracker",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "research-department",
            "Research department",
            "Map collection, synthesis, and briefing into a Scout -> Analyst -> Briefer style workflow pack.",
            "Use when the user wants ongoing research operations without hand-building profiles, vaults, or cron first.",
            ("topic_scope", "source_inbox", "analysis_brief", "delivery_status"),
            "researcher",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "materials-processing",
            "Materials processing",
            "Shape decks, PDFs, spreadsheets, documents, Markdown, and upload-ready packages with observed-only export claims.",
            "Use when the user asks Hermes to turn source material into a document, slide, report, or file package.",
            ("source_inventory", "package_plan", "render_or_handoff", "qa_status"),
            "operator",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
        _standalone_playbook(
            "idea-to-deploy",
            "Idea to deploy",
            (
                "Turn a product idea into scoped implementation, executor selection, verification, review, "
                "and release-readiness tracking."
            ),
            "Use when the user wants an idea prepared for a real coding or delivery path.",
            ("shape_idea", "acceptance_criteria", "executor_selection", "verification_review_release"),
            "handoff-guide",
            context_rule,
            chat_rule,
            fallback_rule,
            evidence_boundary,
        ),
    ]


def _standalone_playbook(
    playbook_id: str,
    display_name: str,
    summary: str,
    use_when: str,
    pipeline: tuple[str, ...],
    owner_role: str,
    workflow_context_rule: str,
    chat_rule: str,
    fallback_rule: str,
    evidence_boundary: str,
) -> dict[str, object]:
    return {
        "schema_version": "playbook_capability/v1",
        "id": playbook_id,
        "display_name": display_name,
        "runtime_claim": "playbook_guidance_not_execution",
        "summary": summary,
        "use_when": use_when,
        "pipeline": list(pipeline),
        "primary_owner_role": owner_role,
        "stage_owners": [owner_role],
        "available_wrapper_actions": ["ask_followup", "show_status", "revise_plan"],
        "first_stage": {
            "id": pipeline[0] if pipeline else "scope_request",
            "title": "Scope the request",
            "owner": owner_role,
            "contract": "playbook_capability/v1",
            "wrapper_actions": ["ask_followup", "show_status"],
        },
        "workflow_context_rule": workflow_context_rule,
        "chat_rule": chat_rule,
        "fallback_rule": fallback_rule,
        "evidence_boundary": evidence_boundary,
        "prepared_is_not": _standalone_evidence_boundaries()["prepared_is_not"],
        "degraded": True,
    }


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
