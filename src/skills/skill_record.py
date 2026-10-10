"""One read path for everything the catalog knows about a skill.

A skill's truth is spread over several tables today: the definition
(`catalog_feature_surfaces.py` / `catalog_definitions.py`), its surface
exposure (`catalog.py`), its harness (`catalog_harnesses.py`), its portability
class (`catalog_portable.py`), its routing policy
(`routing/recommend.py`), the label of that policy's next action
(`routing/action_copy.py`), and its body and reference renderers
(`render.py`). `SkillRecord` assembles those into one value, and
`project(skill, target)` returns the skill's slice of each generated artifact
by calling the producer that writes it.

A record is only a reading of the tables: this module moves no data, and it
never derives one field from another. The policy `evidence_boundary`, the
definition's `safety_rules`, and the harness `overclaim_guards` are separate
fields that agree for only a handful of skills, so the record carries each one
as its table states it.

Migration plan: later changes move each table's per-skill fields into the
record behind this interface, one table at a time, with the generated tree and
`tests/test_skill_record.py` holding the bytes still. The first table moved is
the Agent Skills portable overrides: once a display-name-keyed
`PORTABLE_OVERRIDES` table in `catalog_portable.py`, now the
`portable_overrides` field on each owning definition, which both the record and
the portable renderer read. Today only `packaging.py`
reads through `skill_record(name)` (bodies and references); the docs, Agent
Skills, shortlist and capability-family generators still read their tables
directly and expose the per-skill unit that `project()` calls, so a moved
field reaches them when the generator is pointed at the record.

Not to be confused with `install/manifest.SkillRecord`, which records an
installed file (name, path, sha256, source) and has nothing to do with the
catalog.

Import direction: `packaging.py` imports this module; this module never imports
`packaging.py`. The routing policy, action labels, portability tables, and the
sidecar producers are imported inside the functions that read them, because
they import the skills catalog themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache, partial
import json
from typing import TYPE_CHECKING, Literal

from .catalog import (
    HarnessDefinition,
    SkillDefinition,
    SurfaceExposure,
    builtin_definitions,
    declared_primary_harness,
    harness_definition,
    omh_skill_display_name,
    surface_exposure_for_skill,
    workflow_reference_definitions,
)
from .procedure_rendering import specialist_procedure_reference_markdown
from .render import (
    SkillReferenceTemplate,
    SkillTemplate,
    accessibility_audit_reference_templates,
    adversarial_consensus_reference_templates,
    agent_evaluation_reference_templates,
    agent_debug_reference_templates,
    agent_instructions_reference_templates,
    agent_ops_review_reference_templates,
    agent_skill_template,
    ai_slop_cleaner_reference_templates,
    app_debugging_reference_templates,
    apple_design_reference_templates,
    application_threat_model_reference_templates,
    automation_blueprint_reference_templates,
    award_bar_score_reference_templates,
    buzz_reference_templates,
    buzz_skill,
    code_review_reference_templates,
    commit_pr_authoring_reference_templates,
    context_budget_reference_templates,
    context_reference_templates,
    context_skill,
    data_pipelines_reference_templates,
    deep_interview_reference_templates,
    deep_interview_skill,
    design_reference_templates,
    docs_reference_templates,
    docs_skill,
    domain_engineering_reference_templates,
    external_connector_reference_templates,
    file_ownership_reference_templates,
    frontend_design_reference_templates,
    frontend_performance_reference_templates,
    frontend_refactor_reference_templates,
    git_workflow_reference_templates,
    iac_change_reference_templates,
    idea_to_deploy_reference_templates,
    inference_serving_reference_templates,
    internal_audit_reference_templates,
    jev_preset_reference_templates,
    jit_learn_skill,
    legal_compliance_reference_templates,
    live_incident_reference_templates,
    llm_app_dev_reference_templates,
    long_document_reading_skill,
    long_document_reference_templates,
    loop_reference_templates,
    loop_skill,
    maestro_reference_templates,
    memory_new_skill,
    memory_sync_reference_templates,
    memory_sync_skill,
    mobile_release_reference_templates,
    model_finetuning_reference_templates,
    plan_constitution_reference_templates,
    portable_reference_templates,
    prose_lexicon_reference_templates,
    refactor_plan_reference_templates,
    relational_db_reference_templates,
    release_cut_reference_templates,
    requirement_coverage_reference_templates,
    requirements_quality_reference_templates,
    research_reference_templates,
    review_lens_reference_templates,
    router_reference_templates,
    router_skill,
    scroll_motion_reference_templates,
    security_event_response_reference_templates,
    security_safety_review_reference_templates,
    strategy_brief_reference_templates,
    structural_search_skill,
    tech_debt_audit_reference_templates,
    todo_checklist_reference_templates,
    ultraqa_reference_templates,
    ultrawork_reference_templates,
    ultrawork_skill,
    verification_gate_reference_templates,
    wiki_reference_templates,
    wiki_skill,
    workflow_full_contract_reference,
    workflow_reference_skill_lines,
    workflow_skill,
)

if TYPE_CHECKING:
    from ..routing.recommend import RecommendationPolicy

ProjectionTarget = Literal[
    "hermes", "agent-skills", "workflows-doc", "roles-doc", "shortlist", "capability-family",
]
# Relative path -> text. File targets key by the path under their generated
# root (`skills/`, `agent-skills/`); document and sidecar targets key by the
# repo-relative file and hold this skill's slice of it.
ProjectedFiles = Mapping[str, str]
PolicySource = Literal["skill", "category", "role", "default"]

# Skills whose SKILL.md body has its own renderer; every other skill renders
# through the generic `workflow_skill(name)`.
_BESPOKE_BODIES: dict[str, Callable[[], SkillTemplate]] = {
    "oh-my-hermes": router_skill,
    "context": context_skill,
    "deep-interview": deep_interview_skill,
    "product-docs": docs_skill,
    "jit-learn": jit_learn_skill,
    "loop": loop_skill,
    "long-document-reading": long_document_reading_skill,
    "memory-new": memory_new_skill,
    "memory-sync": memory_sync_skill,
    "wiki": wiki_skill,
    "buzz": buzz_skill,
    "codebase-onboarding": partial(structural_search_skill, "codebase-onboarding"),
    "codegraph-refresh": partial(structural_search_skill, "codegraph-refresh"),
    "ultrawork": ultrawork_skill,
}


def _procedure_reference_templates() -> list[SkillReferenceTemplate]:
    return [
        SkillReferenceTemplate(
            definition.name,
            "references/procedure.md",
            specialist_procedure_reference_markdown(definition),
        )
        for definition in workflow_reference_definitions()
        if definition.procedure_steps
    ]


def _full_contract_reference_templates() -> list[SkillReferenceTemplate]:
    return [
        SkillReferenceTemplate(
            definition.name,
            "references/full-contract.md",
            workflow_full_contract_reference(definition, definition.name),
        )
        for definition in workflow_reference_definitions()
        if definition.progressive_disclosure
    ]


# Every reference producer. `reference_templates_in_producer_order()` yields
# in this order and `builtin_skill_reference_templates()` is that sequence, so
# the installer writes references in this order by construction. A producer
# may yield references for several skills.
REFERENCE_PRODUCERS: tuple[Callable[[], list[SkillReferenceTemplate]], ...] = (
    router_reference_templates,
    wiki_reference_templates,
    code_review_reference_templates,
    context_reference_templates,
    docs_reference_templates,
    context_budget_reference_templates,
    buzz_reference_templates,
    loop_reference_templates,
    long_document_reference_templates,
    application_threat_model_reference_templates,
    live_incident_reference_templates,
    app_debugging_reference_templates,
    agent_debug_reference_templates,
    commit_pr_authoring_reference_templates,
    git_workflow_reference_templates,
    relational_db_reference_templates,
    security_event_response_reference_templates,
    agent_instructions_reference_templates,
    iac_change_reference_templates,
    data_pipelines_reference_templates,
    model_finetuning_reference_templates,
    mobile_release_reference_templates,
    internal_audit_reference_templates,
    release_cut_reference_templates,
    automation_blueprint_reference_templates,
    external_connector_reference_templates,
    verification_gate_reference_templates,
    security_safety_review_reference_templates,
    legal_compliance_reference_templates,
    todo_checklist_reference_templates,
    memory_sync_reference_templates,
    maestro_reference_templates,
    adversarial_consensus_reference_templates,
    ultraqa_reference_templates,
    ultrawork_reference_templates,
    idea_to_deploy_reference_templates,
    llm_app_dev_reference_templates,
    _procedure_reference_templates,
    _full_contract_reference_templates,
    research_reference_templates,
    design_reference_templates,
    apple_design_reference_templates,
    award_bar_score_reference_templates,
    agent_ops_review_reference_templates,
    inference_serving_reference_templates,
    tech_debt_audit_reference_templates,
    frontend_performance_reference_templates,
    scroll_motion_reference_templates,
    frontend_design_reference_templates,
    accessibility_audit_reference_templates,
    agent_evaluation_reference_templates,
    strategy_brief_reference_templates,
    refactor_plan_reference_templates,
    frontend_refactor_reference_templates,
    ai_slop_cleaner_reference_templates,
    domain_engineering_reference_templates,
    # Issue #1714: one reference per skill carrying a mechanism the body
    # only points at. Reference files are measured outside
    # FULL_PROFILE_SKILL_BODY_CHAR_LIMIT, so each capability costs one
    # pointer line in the always-loaded budget and nothing more.
    requirement_coverage_reference_templates,
    deep_interview_reference_templates,
    file_ownership_reference_templates,
    review_lens_reference_templates,
    requirements_quality_reference_templates,
    prose_lexicon_reference_templates,
    plan_constitution_reference_templates,
    jev_preset_reference_templates,
)


@dataclass(frozen=True)
class SkillRecord:
    name: str
    definition: SkillDefinition
    exposure: SurfaceExposure
    # None when the catalog declares no harness; routing's fallback harness is
    # not a fact about the skill (see `declared_primary_harness`).
    harness: HarnessDefinition | None
    portability: str
    portable_overrides: Mapping[str, tuple[str, ...]]
    policy: RecommendationPolicy
    policy_source: PolicySource
    next_action_label: str
    body: Callable[[], SkillTemplate]
    references: Callable[[], tuple[SkillReferenceTemplate, ...]]

    @property
    def display_name(self) -> str:
        return omh_skill_display_name(self.name)


def skill_record(name: str) -> SkillRecord:
    """The record for one builtin skill; KeyError for a name the catalog lacks."""
    return _records_by_name()[name]


def skill_records() -> tuple[SkillRecord, ...]:
    """Every builtin skill's record, in catalog order."""
    return _skill_records_cached()


def skill_body_renderer(name: str) -> Callable[[], SkillTemplate]:
    """The callable that renders `name`'s SKILL.md: its bespoke renderer, else the generic one."""
    return _BESPOKE_BODIES.get(name) or partial(workflow_skill, name)


def reference_templates_in_producer_order() -> list[SkillReferenceTemplate]:
    """Every installed reference, in `REFERENCE_PRODUCERS` order."""
    return [template for producer in REFERENCE_PRODUCERS for template in producer()]


def project(skill: SkillRecord, target: ProjectionTarget) -> ProjectedFiles:
    """`skill`'s slice of one generated target, produced by that target's own producer."""
    if target == "hermes":
        return _project_hermes(skill)
    if target == "agent-skills":
        return _project_agent_skills(skill)
    if target == "workflows-doc":
        return _project_workflows_doc(skill)
    if target == "roles-doc":
        return _project_roles_doc(skill)
    if target == "shortlist":
        return _project_shortlist(skill)
    if target == "capability-family":
        return _project_capability_family(skill)
    raise ValueError(f"unknown projection target: {target}")


@lru_cache(maxsize=1)
def _skill_records_cached() -> tuple[SkillRecord, ...]:
    return tuple(_build_record(definition) for definition in builtin_definitions())


@lru_cache(maxsize=1)
def _records_by_name() -> dict[str, SkillRecord]:
    return {record.name: record for record in _skill_records_cached()}


@lru_cache(maxsize=1)
def _reference_producers_by_skill() -> dict[str, tuple[Callable[[], list[SkillReferenceTemplate]], ...]]:
    producers: dict[str, list[Callable[[], list[SkillReferenceTemplate]]]] = {}
    for producer in REFERENCE_PRODUCERS:
        for template in producer():
            owned = producers.setdefault(template.skill_name, [])
            if producer not in owned:
                owned.append(producer)
    return {name: tuple(owned) for name, owned in producers.items()}


def _skill_references(name: str) -> tuple[SkillReferenceTemplate, ...]:
    return tuple(
        template
        for producer in _reference_producers_by_skill().get(name, ())
        for template in producer()
        if template.skill_name == name
    )


def _build_record(definition: SkillDefinition) -> SkillRecord:
    from ..routing.action_copy import next_action_label
    from ..routing.recommend import policy_with_source
    from .catalog_portable import skill_portability

    name = definition.name
    harness_name = declared_primary_harness(name)
    policy, source = policy_with_source(definition)
    return SkillRecord(
        name=name,
        definition=definition,
        exposure=surface_exposure_for_skill(name),
        harness=harness_definition(harness_name) if harness_name else None,
        portability=skill_portability(name),
        portable_overrides=definition.portable_overrides,
        policy=policy,
        policy_source=source,
        next_action_label=next_action_label(policy.next_action),
        body=skill_body_renderer(name),
        references=partial(_skill_references, name),
    )


def _project_hermes(skill: SkillRecord) -> ProjectedFiles:
    if not skill.exposure.install_visibility:
        return {}
    body = skill.body()
    files = {f"{omh_skill_display_name(body.name)}/SKILL.md": body.content}
    files.update(
        {
            f"{omh_skill_display_name(template.skill_name)}/{template.relative_path}": template.content
            for template in skill.references()
        }
    )
    return files


def _project_agent_skills(skill: SkillRecord) -> ProjectedFiles:
    from .catalog_portable import portable_skill_names

    if skill.display_name not in portable_skill_names():
        return {}
    body = agent_skill_template(skill.definition)
    files = {f"{body.name}/SKILL.md": body.content}
    files.update(
        {
            f"{template.skill_name}/{template.relative_path}": template.content
            for template in portable_reference_templates(skill.references())
        }
    )
    return files


def _project_workflows_doc(skill: SkillRecord) -> ProjectedFiles:
    if skill.name not in {definition.name for definition in workflow_reference_definitions()}:
        return {}
    return {"docs/WORKFLOWS.md": "\n".join(workflow_reference_skill_lines(skill.definition))}


def _project_roles_doc(skill: SkillRecord) -> ProjectedFiles:
    """The sections of the roles that list this skill; ROLES.md has no per-skill unit."""
    from ..catalogs.roles import role_definitions, role_reference_lines

    sections = [
        "\n".join(role_reference_lines(role))
        for role in role_definitions()
        if skill.name in role.primary_skills
    ]
    return {"docs/ROLES.md": "\n".join(sections)} if sections else {}


def _project_shortlist(skill: SkillRecord) -> ProjectedFiles:
    from ..routing.skill_shortlist_sidecar import skill_shortlist_entry

    entry = skill_shortlist_entry(skill.name)
    if entry is None:
        return {}
    # Same serializer settings as `standalone_skill_shortlist_json`; with
    # indent=0 every nesting level is flush, so the entry appears verbatim.
    text = json.dumps(entry, ensure_ascii=False, indent=0, sort_keys=True, separators=(",", ":"))
    return {"src/plugin_bundle/omh/tools/skill_shortlist.json": text}


def _project_capability_family(skill: SkillRecord) -> ProjectedFiles:
    """The family entries that list this skill; the sidecar is per family, not per skill."""
    from ..capabilities.families import capability_family_projection

    families = [
        family
        for family in capability_family_projection()["families"]
        if skill.name in family.get("primary_workflows", ())
    ]
    if not families:
        return {}
    text = json.dumps(families, ensure_ascii=False, indent=1, sort_keys=True)
    return {"src/plugin_bundle/omh/tools/capability_families.json": text}
