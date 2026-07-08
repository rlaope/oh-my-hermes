from __future__ import annotations

from functools import lru_cache
from typing import Iterable, cast

from ..plugin_bundle.omh.awareness import awareness_lane_examples, awareness_primer_payload
from ..skills.catalog import installable_skill_names

CAPABILITY_FAMILY_SCHEMA_VERSION = "omh_capability_families/v1"

CONCEPTUAL_WORKFLOW_SURFACES = {
    "request-to-handoff",
    "executor selection",
    "coding runtime handoff",
}

_FAMILY_DEFINITIONS = (
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
        ),
        "next_action": "clarify_or_prepare_plan",
        "example_prompt": "Make onboarding feel smoother.",
        "not_evidence_until_observed": ("plan acceptance", "executor dispatch", "verification"),
        "route_summary": "Clarify the goal, choose the planning depth, and show the next concrete action.",
    },
    {
        "id": "learn_and_gather",
        "label": "Learn and gather",
        "owner_role": "researcher",
        "source_lanes": ("research_and_ops",),
        "use_for": "Source finding, web research, papers, customer signals, and briefings.",
        "primary_workflows": ("source-finder", "web-research", "paper-learning", "data-analysis", "research-department", "feedback-triage"),
        "next_action": "gather_source_backed_evidence",
        "example_prompt": "Find papers, datasets, and repos for this topic.",
        "not_evidence_until_observed": ("source retrieval", "source verification", "decision approval"),
        "route_summary": "Name the source/synthesis split before summarizing or planning from the material.",
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
        "not_evidence_until_observed": ("external write", "memory mutation", "connector I/O", "source verification"),
        "route_summary": "Prepare notes and hints without claiming writes.",
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
            "content-operator",
            "media-input-operator",
        ),
        "next_action": "prepare_material_or_visual_card",
        "example_prompt": "Make a PR summary card for reviewers.",
        "not_evidence_until_observed": ("frontend implementation", "accessibility PASS", "file export", "image generation", "visual QA", "delivery"),
        "route_summary": "Prepare the copy, prompt, package, or QA contract before claiming generated output.",
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
            "executor-runtime-readiness",
            "code-review",
            "build-failure-triage",
            "verification-gate",
            "security-safety-review",
            "team",
            "ultrawork",
            "ultraqa",
        ),
        "executor_choices": ("Codex", "Claude Code", "Hermes", "generic runtime"),
        "next_action": "prepare_scoped_coding_handoff",
        "example_prompt": "Turn this issue into a PR-ready plan and hand it to implementation.",
        "not_evidence_until_observed": ("executor dispatch", "implementation", "review", "CI", "merge"),
        "route_summary": "Choose the coding owner only after scope is concrete, then track observed evidence separately.",
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
            "github-event-ops",
            "agent-board",
            "gateway-intent-card",
            "voice-operator",
            "browser-operator",
            "workspace-file-operator",
            "command-operator",
            "connector-operator",
            "live-info-operator",
            "agent-ops-review",
            "agent-debug",
            "failure-signal-audit",
            "instinct-ledger",
            "agent-evaluation",
            "rules-distill",
            "context-budget-review",
            "toolbelt-readiness",
            "external-connector-readiness",
            "prompt-import-readiness",
            "skill-scout",
            "skill-health",
            "workflow-learning",
            "memory-curation-review",
        ),
        "next_action": "show_status_or_prepare_operating_card",
        "example_prompt": "Why did this route to plan? Make it a regression.",
        "not_evidence_until_observed": ("schedule creation", "connector I/O", "runtime load", "skill patch approval"),
        "route_summary": "Show status, repair, schedule, or learning shape without claiming runtime actions happened.",
    },
)

_WORKFLOW_FAMILY_OVERRIDES = {
    "oh-my-hermes": "plan_and_decide",
    "deep-interview": "plan_and_decide",
    "plan": "plan_and_decide",
    "ralplan": "plan_and_decide",
    "ralph": "plan_and_decide",
    "ultragoal": "plan_and_decide",
    "loop": "plan_and_decide",
    "performance-goal": "plan_and_decide",
    "strategy-brief": "plan_and_decide",
    "codebase-onboarding": "plan_and_decide",
    "codegraph-refresh": "plan_and_decide",
    "source-finder": "learn_and_gather",
    "data-analysis": "learn_and_gather",
    "command-operator": "operate_and_observe",
    "connector-operator": "operate_and_observe",
    "live-info-operator": "operate_and_observe",
    "workspace-audit": "operate_and_observe",
    "production-audit": "operate_and_observe",
    "agent-evaluation": "operate_and_observe",
    "rules-distill": "operate_and_observe",
    "context-budget-review": "operate_and_observe",
    "agent-debug": "operate_and_observe",
    "failure-signal-audit": "operate_and_observe",
    "instinct-ledger": "operate_and_observe",
    "skill-scout": "operate_and_observe",
    "skill-health": "operate_and_observe",
    "web-research": "learn_and_gather",
    "best-practice-research": "learn_and_gather",
    "autoresearch-goal": "learn_and_gather",
    "research-brief": "learn_and_gather",
    "research-department": "learn_and_gather",
    "paper-learning": "learn_and_gather",
    "feedback-triage": "learn_and_gather",
    "meeting-brief": "learn_and_gather",
    "wiki": "retain_knowledge",
    "materials-package": "create_materials_and_visuals",
    "report-package": "create_materials_and_visuals",
    "deliverable-package": "create_materials_and_visuals",
    "content-operator": "create_materials_and_visuals",
    "media-input-operator": "create_materials_and_visuals",
    "img-summary": "create_materials_and_visuals",
    "frontend": "create_materials_and_visuals",
    "accessibility-audit": "create_materials_and_visuals",
    "visual-qa": "create_materials_and_visuals",
    "idea-to-deploy": "delegate_coding_and_ship",
    "ultraprocess": "delegate_coding_and_ship",
    "code-review": "delegate_coding_and_ship",
    "build-failure-triage": "delegate_coding_and_ship",
    "verification-gate": "delegate_coding_and_ship",
    "security-safety-review": "delegate_coding_and_ship",
    "team": "delegate_coding_and_ship",
    "ultrawork": "delegate_coding_and_ship",
    "ultraqa": "delegate_coding_and_ship",
    "ai-slop-cleaner": "delegate_coding_and_ship",
    "executor-runtime-readiness": "delegate_coding_and_ship",
    "request-to-handoff": "delegate_coding_and_ship",
    "executor selection": "delegate_coding_and_ship",
    "coding runtime handoff": "delegate_coding_and_ship",
    "cto-loop": "delegate_coding_and_ship",
    "deploy-and-monitor": "delegate_coding_and_ship",
    "github-event-ops": "operate_and_observe",
    "automation-blueprint": "operate_and_observe",
    "agent-board": "operate_and_observe",
    "gateway-intent-card": "operate_and_observe",
    "voice-operator": "operate_and_observe",
    "browser-operator": "operate_and_observe",
    "workspace-file-operator": "operate_and_observe",
    "command-operator": "operate_and_observe",
    "connector-operator": "operate_and_observe",
    "live-info-operator": "operate_and_observe",
    "external-connector-readiness": "operate_and_observe",
    "prompt-import-readiness": "operate_and_observe",
    "toolbelt-readiness": "operate_and_observe",
    "harness-session-inventory": "operate_and_observe",
    "ops-observability-card": "operate_and_observe",
    "agent-ops-review": "operate_and_observe",
    "memory-curation-review": "operate_and_observe",
    "workflow-learning": "operate_and_observe",
    "doctor": "operate_and_observe",
    "skill": "operate_and_observe",
    "ask": "operate_and_observe",
    "cancel": "operate_and_observe",
    "operating-rhythm": "operate_and_observe",
    "ops-review": "operate_and_observe",
    "reliability-review": "operate_and_observe",
}


def capability_family_projection(available_workflows: Iterable[str] | None = None) -> dict[str, object]:
    """Return the user-facing OMH capability-family projection."""
    return _copy_capability_family_projection(
        _capability_family_projection_cached(_available_workflows_key(available_workflows))
    )


@lru_cache(maxsize=128)
def _capability_family_projection_cached(available_key: tuple[str, ...] | None) -> dict[str, object]:
    awareness = awareness_primer_payload()
    lane_by_id = {
        str(lane.get("id")): lane
        for lane in _dict_list(awareness.get("lanes", []))
    }
    available = _available_workflows_from_key(available_key)
    families = [
        _family_payload(definition, lane_by_id, available)
        for definition in _FAMILY_DEFINITIONS
    ]
    workflow_to_family = _workflow_to_family(families, lane_by_id, available)
    return {
        "schema_version": CAPABILITY_FAMILY_SCHEMA_VERSION,
        "determinism": "static_projection_no_runtime_clock",
        "purpose": (
            "User-facing front-door families for explaining OMH without making normal users learn backend commands."
        ),
        "families": families,
        "workflow_to_family": workflow_to_family,
        "family_order": [str(family["id"]) for family in families],
        "claim_boundary": (
            "Capability families are routing and handoff guidance only; prepared cards, prompts, or handoffs "
            "are not observed execution, generation, review, CI, merge, delivery, or Hermes plugin-use evidence."
        ),
    }


def capability_family_cards(available_workflows: Iterable[str] | None = None) -> list[dict[str, object]]:
    """Return compact cards for picker, quickstart, and README-like surfaces."""
    projection = _capability_family_projection_cached(_available_workflows_key(available_workflows))
    return _copy_family_cards(_dict_list(projection.get("families", [])))


def family_for_workflow(workflow: str, available_workflows: Iterable[str] | None = None) -> dict[str, object]:
    """Return the family card for one workflow or an empty dict when unknown."""
    key = str(workflow or "").strip()
    if not key:
        return {}
    projection = _capability_family_projection_cached(_available_workflows_key(available_workflows))
    workflow_to_family = _string_mapping(projection.get("workflow_to_family", {}))
    family_id = workflow_to_family.get(key)
    if not family_id:
        family_id = workflow_to_family.get(key.casefold())
    if not family_id:
        return {}
    for family in _dict_list(projection.get("families", [])):
        if family.get("id") == family_id:
            return _copy_family_payload(family)
    return {}


def family_id_for_workflow(workflow: str) -> str:
    """Return just the family id for compact skill capability metadata."""
    family = family_for_workflow(workflow)
    return str(family.get("id", ""))


def _available_workflows(available_workflows: Iterable[str] | None) -> set[str]:
    if available_workflows is None:
        return set(installable_skill_names()) | CONCEPTUAL_WORKFLOW_SURFACES | {"oh-my-hermes"}
    return {str(item) for item in available_workflows if str(item)} | CONCEPTUAL_WORKFLOW_SURFACES | {"oh-my-hermes"}


def _available_workflows_key(available_workflows: Iterable[str] | None) -> tuple[str, ...] | None:
    if available_workflows is None:
        return None
    return tuple(sorted({str(item) for item in available_workflows if str(item)}))


def _available_workflows_from_key(available_key: tuple[str, ...] | None) -> set[str]:
    if available_key is None:
        return _available_workflows(None)
    return set(available_key) | CONCEPTUAL_WORKFLOW_SURFACES | {"oh-my-hermes"}


def _copy_capability_family_projection(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    copied["families"] = _copy_family_cards(_dict_list(payload.get("families", [])))
    copied["workflow_to_family"] = _string_mapping(payload.get("workflow_to_family", {}))
    copied["family_order"] = _string_list(payload.get("family_order", []))
    return copied


def _copy_family_cards(families: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_copy_family_payload(family) for family in families]


def _copy_family_payload(family: dict[str, object]) -> dict[str, object]:
    copied = dict(family)
    for key in (
        "source_lanes",
        "primary_workflows",
        "not_evidence_until_observed",
        "source_examples",
        "executor_choices",
    ):
        if key in copied:
            copied[key] = _string_list(copied.get(key, []))
    return copied


def _family_payload(
    definition: dict[str, object],
    lane_by_id: dict[str, dict[str, object]],
    available: set[str],
) -> dict[str, object]:
    source_lanes = _string_tuple(definition.get("source_lanes", ()))
    source_workflows = _source_workflows(source_lanes, lane_by_id, available)
    family_id = str(definition["id"])
    primary_workflows = [
        workflow
        for workflow in _dedupe([*_string_tuple(definition.get("primary_workflows", ())), *source_workflows])
        if workflow in available and _workflow_belongs_to_family(workflow, family_id, source_lanes)
    ]
    payload = {
        "id": family_id,
        "label": str(definition["label"]),
        "owner_role": str(definition["owner_role"]),
        "source_lanes": list(source_lanes),
        "use_for": str(definition["use_for"]),
        "primary_workflows": primary_workflows,
        "next_action": str(definition["next_action"]),
        "example_prompt": str(definition["example_prompt"]),
        "route_summary": str(definition["route_summary"]),
        "not_evidence_until_observed": list(_string_tuple(definition.get("not_evidence_until_observed", ()))),
        "source_examples": [
            example
            for lane_id in source_lanes
            for example in awareness_lane_examples(lane_id)
        ][:4],
    }
    executor_choices = _string_tuple(definition.get("executor_choices", ()))
    if executor_choices:
        payload["executor_choices"] = list(executor_choices)
    return payload


def _source_workflows(
    source_lanes: tuple[str, ...],
    lane_by_id: dict[str, dict[str, object]],
    available: set[str],
) -> list[str]:
    workflows: list[str] = []
    for lane_id in source_lanes:
        lane = lane_by_id.get(lane_id, {})
        for workflow in _string_list(lane.get("skills", [])):
            if workflow in available:
                workflows.append(workflow)
    return workflows


def _workflow_to_family(
    families: list[dict[str, object]],
    lane_by_id: dict[str, dict[str, object]],
    available: set[str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    family_ids = {str(family["id"]) for family in families}
    for workflow, family_id in sorted(_WORKFLOW_FAMILY_OVERRIDES.items()):
        if workflow in available and family_id in family_ids:
            mapping[workflow] = family_id
            mapping[workflow.casefold()] = family_id
    for family in families:
        family_id = str(family["id"])
        for workflow in _string_list(family.get("primary_workflows", [])):
            mapping.setdefault(workflow, family_id)
            mapping.setdefault(workflow.casefold(), family_id)
    for lane in lane_by_id.values():
        lane_id = str(lane.get("id", ""))
        default_family = _default_family_for_source_lane(lane_id)
        if not default_family:
            continue
        for workflow in _string_list(lane.get("skills", [])):
            if workflow in available:
                mapping.setdefault(workflow, default_family)
                mapping.setdefault(workflow.casefold(), default_family)
    return mapping


def _workflow_belongs_to_family(workflow: str, family_id: str, source_lanes: tuple[str, ...]) -> bool:
    override = _WORKFLOW_FAMILY_OVERRIDES.get(workflow)
    if override:
        return override == family_id
    return any(_default_family_for_source_lane(lane_id) == family_id for lane_id in source_lanes)


def _default_family_for_source_lane(lane_id: str) -> str:
    for definition in _FAMILY_DEFINITIONS:
        if lane_id in _string_tuple(definition.get("source_lanes", ())):
            return str(definition["id"])
    return ""


def _dedupe(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, object], item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item))
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    return ()


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(key) and str(item)}
