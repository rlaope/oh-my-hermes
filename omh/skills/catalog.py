from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    triggers: tuple[str, ...]
    use_when: str


_DEFINITIONS = [
    SkillDefinition(
        "oh-my-hermes",
        "Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.",
        ("oh-my-hermes", "omh", "skill routing", "workflow routing"),
        "Use as the top-level router when a request references oh-my-hermes, installed workflows, or ambiguous workflow routing.",
    ),
    SkillDefinition(
        "ralph",
        "Hermes Ralph workflow: persistent execution with verification and review.",
        ("ralph", "$ralph", "finish until done", "persistent execution", "self-referential loop"),
        "Use after scope is concrete and the user wants one owner to continue through implementation and verification.",
    ),
    SkillDefinition(
        "ultragoal",
        "Hermes Ultragoal workflow: file-backed durable goal ledgers.",
        ("ultragoal", "$ultragoal", "durable goal", "multi-goal", "goal ledger"),
        "Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.",
    ),
    SkillDefinition(
        "deep-interview",
        "Hermes Deep Interview workflow: one-question-at-a-time clarification.",
        ("deep-interview", "$deep-interview", "interview", "don't assume", "clarify"),
        "Use before planning or execution when requirements are materially ambiguous.",
    ),
    SkillDefinition(
        "team",
        "Hermes Team workflow: coordinated parallel or sequential work lanes.",
        ("team", "$team", "swarm", "parallel agents", "coordinated workers"),
        "Use when multiple independent lanes materially improve throughput or verification.",
    ),
    SkillDefinition(
        "ultraqa",
        "Hermes UltraQA workflow: adversarial QA and fix loops.",
        ("ultraqa", "$ultraqa", "adversarial qa", "hostile scenarios", "e2e qa"),
        "Use when the task needs adversarial test scenarios, verification, and fix loops.",
    ),
    SkillDefinition(
        "plan",
        "Hermes Plan workflow: structured planning before execution.",
        ("plan", "$plan", "implementation plan", "strategy", "task breakdown"),
        "Use for structured planning when implementation is not ready to start safely.",
    ),
    SkillDefinition(
        "ralplan",
        "Hermes Ralplan workflow: consensus planning with review gates.",
        ("ralplan", "$ralplan", "consensus plan", "reviewed plan"),
        "Use when requirements are clear enough for planning but architecture, risks, or tests need review.",
    ),
    SkillDefinition(
        "code-review",
        "Hermes Code Review workflow: bug-first review with evidence.",
        ("code-review", "$code-review", "review", "audit", "find bugs"),
        "Use for review-shaped requests; findings come first and must cite concrete evidence.",
    ),
    SkillDefinition(
        "ai-slop-cleaner",
        "Hermes AI slop cleaner workflow: behavior-preserving cleanup.",
        ("ai-slop-cleaner", "$ai-slop-cleaner", "cleanup", "deslop", "refactor"),
        "Use for behavior-preserving cleanup with tests before and after edits.",
    ),
    SkillDefinition(
        "best-practice-research",
        "Hermes adaptation for bounded official/upstream best-practice research.",
        ("best-practice-research", "best practice", "official docs", "upstream guidance"),
        "Use when correctness depends on current official or upstream guidance.",
    ),
    SkillDefinition(
        "autoresearch-goal",
        "Hermes adaptation for durable research-goal execution.",
        ("autoresearch-goal", "research goal", "durable research", "critic research"),
        "Use for validator-gated research that needs durable artifacts.",
    ),
    SkillDefinition(
        "performance-goal",
        "Hermes adaptation for measurable performance-goal execution.",
        ("performance-goal", "performance goal", "latency", "throughput", "benchmark"),
        "Use when the goal is measurable performance improvement with evaluator evidence.",
    ),
    SkillDefinition(
        "wiki",
        "Hermes adaptation for maintaining a project-local markdown wiki.",
        ("wiki", "project wiki", "memory", "notes"),
        "Use to capture durable project knowledge in markdown artifacts.",
    ),
    SkillDefinition(
        "ask",
        "Hermes adaptation for consulting an external advisor when configured.",
        ("ask", "$ask", "external advisor", "claude", "gemini"),
        "Use only when an external advisor is configured and would materially improve the answer.",
    ),
    SkillDefinition(
        "cancel",
        "Hermes adaptation for ending active workflow state cleanly.",
        ("cancel", "$cancel", "stop", "abort"),
        "Use to cleanly end active adapted workflow state.",
    ),
    SkillDefinition(
        "skill",
        "Hermes adaptation for managing local skills.",
        ("skill", "$skill", "skills", "manage skills"),
        "Use for local skill listing, search, add, remove, or edit tasks.",
    ),
    SkillDefinition(
        "doctor",
        "Hermes adaptation for diagnosing oh-my-hermes installation health.",
        ("doctor", "$doctor", "diagnose omh", "installation health"),
        "Use to diagnose OMH installation and Hermes config registration.",
    ),
]


def builtin_definitions() -> list[SkillDefinition]:
    return list(_DEFINITIONS)


CORE_SKILLS = [definition.name for definition in _DEFINITIONS]
DESCRIPTIONS = {definition.name: definition.description for definition in _DEFINITIONS}
