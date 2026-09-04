from __future__ import annotations

from functools import lru_cache

from .catalog import installable_skill_definitions, workflow_reference_definitions
from .procedure_rendering import specialist_procedure_reference_markdown
from .render import (
    SkillReferenceTemplate,
    SkillTemplate,
    adversarial_consensus_reference_templates,
    buzz_reference_templates,
    buzz_skill,
    code_review_reference_templates,
    context_budget_reference_templates,
    context_reference_templates,
    context_skill,
    deep_interview_skill,
    docs_reference_templates,
    docs_skill,
    ai_slop_cleaner_reference_templates,
    agent_ops_review_reference_templates,
    award_bar_score_reference_templates,
    design_reference_templates,
    inference_serving_reference_templates,
    tech_debt_audit_reference_templates,
    frontend_performance_reference_templates,
    accessibility_audit_reference_templates,
    agent_evaluation_reference_templates,
    strategy_brief_reference_templates,
    refactor_plan_reference_templates,
    frontend_refactor_reference_templates,
    domain_engineering_reference_templates,
    idea_to_deploy_reference_templates,
    jit_learn_skill,
    llm_app_dev_reference_templates,
    loop_reference_templates,
    loop_skill,
    maestro_reference_templates,
    memory_new_skill,
    memory_sync_skill,
    research_reference_templates,
    router_reference_templates,
    router_skill,
    structural_search_skill,
    ultrawork_reference_templates,
    ultrawork_skill,
    wiki_reference_templates,
    wiki_skill,
    workflow_skill,
)


def builtin_skill_templates() -> list[SkillTemplate]:
    return list(_builtin_skill_templates_cached())


def builtin_skill_reference_templates() -> list[SkillReferenceTemplate]:
    return [
        *router_reference_templates(),
        *wiki_reference_templates(),
        *code_review_reference_templates(),
        *context_reference_templates(),
        *docs_reference_templates(),
        *context_budget_reference_templates(),
        *buzz_reference_templates(),
        *loop_reference_templates(),
        *maestro_reference_templates(),
        *adversarial_consensus_reference_templates(),
        *ultrawork_reference_templates(),
        *idea_to_deploy_reference_templates(),
        *llm_app_dev_reference_templates(),
        *[
            SkillReferenceTemplate(
                definition.name,
                "references/procedure.md",
                specialist_procedure_reference_markdown(definition),
            )
            for definition in workflow_reference_definitions()
            if definition.procedure_steps
        ],
        *research_reference_templates(),
        *design_reference_templates(),
        *award_bar_score_reference_templates(),
        *agent_ops_review_reference_templates(),
        *inference_serving_reference_templates(),
        *tech_debt_audit_reference_templates(),
        *frontend_performance_reference_templates(),
        *accessibility_audit_reference_templates(),
        *agent_evaluation_reference_templates(),
        *strategy_brief_reference_templates(),
        *refactor_plan_reference_templates(),
        *frontend_refactor_reference_templates(),
        *ai_slop_cleaner_reference_templates(),
        *domain_engineering_reference_templates(),
    ]


def _skill_template_for(name: str) -> SkillTemplate:
    if name == "context":
        return context_skill()
    if name == "deep-interview":
        return deep_interview_skill()
    if name == "product-docs":
        return docs_skill()
    if name == "jit-learn":
        return jit_learn_skill()
    if name == "loop":
        return loop_skill()
    if name == "memory-new":
        return memory_new_skill()
    if name == "memory-sync":
        return memory_sync_skill()
    if name == "wiki":
        return wiki_skill()
    if name == "buzz":
        return buzz_skill()
    if name in ("codebase-onboarding", "codegraph-refresh"):
        return structural_search_skill(name)
    if name == "ultrawork":
        return ultrawork_skill()
    return workflow_skill(name)


@lru_cache(maxsize=1)
def _builtin_skill_templates_cached() -> tuple[SkillTemplate, ...]:
    names = [definition.name for definition in installable_skill_definitions()]
    return (router_skill(), *[_skill_template_for(name) for name in names if name != "oh-my-hermes"])
