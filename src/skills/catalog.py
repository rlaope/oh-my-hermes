from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    triggers: tuple[str, ...]
    use_when: str


@dataclass(frozen=True)
class HarnessDefinition:
    name: str
    purpose: str
    use_when: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    verification: tuple[str, ...]
    fallback: str
    artifact_events: tuple[str, ...]
    delegation_expectation: str
    privacy_default: str


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


_HARNESSES = [
    HarnessDefinition(
        "coding-handling",
        "Route implementation requests through scoped context, edit discipline, tests, review, and evidence.",
        "Use when the user asks Hermes to write, modify, debug, refactor, or review code.",
        ("task statement", "repo context", "constraints", "target files or discovered touchpoints"),
        ("changed files", "verification evidence", "remaining risks"),
        ("requested behavior is implemented", "tests or checks pass", "known gaps are reported"),
        ("run the smallest relevant tests", "inspect generated skill output when routing changed"),
        "If the request is underspecified, ask one concise clarification question before editing.",
        ("run_started", "files_changed", "verification_recorded"),
        "Record delegation only when Hermes exposes a separate coding, review, or verification lane.",
        "metadata_only",
    ),
    HarnessDefinition(
        "goal-execution",
        "Keep long-running work tied to explicit goals, checkpoints, and durable evidence.",
        "Use when the task has multiple milestones, durable state, or finish-until-done pressure.",
        ("goal statement", "acceptance criteria", "current checkpoint", "blocked or pending stories"),
        ("goal ledger updates", "checkpoint evidence", "completion or blocker summary"),
        ("current goal is complete or explicitly blocked", "checkpoint evidence is recorded"),
        ("compare artifacts against acceptance criteria", "record fresh evidence before completion"),
        "If Hermes has no goal tool, use a local checklist or file-backed ledger.",
        ("goal_started", "checkpoint_recorded", "goal_completed_or_blocked"),
        "Record goal/delegation participants only when the active Hermes runtime exposes them.",
        "metadata_only",
    ),
    HarnessDefinition(
        "planning",
        "Turn clarified requirements into an execution-ready plan with tradeoffs and tests.",
        "Use before implementation when architecture, sequencing, or validation shape matters.",
        ("requirements", "constraints", "known facts", "non-goals"),
        ("PRD or plan", "test strategy", "handoff guidance"),
        ("plan has acceptance criteria", "risks and alternatives are explicit"),
        ("review option consistency", "verify testability before execution"),
        "If consensus review is unavailable, do a sequential planner -> reviewer pass.",
        ("plan_started", "options_reviewed", "handoff_recorded"),
        "Record planner, architect, or reviewer delegation only when observed in Hermes metadata or wrapper logs.",
        "metadata_only",
    ),
    HarnessDefinition(
        "deep-interview",
        "Clarify intent and boundaries one question at a time before planning or execution.",
        "Use when intent, scope, non-goals, or decision authority are unclear.",
        ("initial idea", "current ambiguity", "known repo facts"),
        ("clarified spec", "non-goals", "decision boundaries", "acceptance criteria"),
        ("ambiguity is low enough", "non-goals and decision boundaries are explicit"),
        ("pressure-test assumptions", "capture transcript or summary"),
        "If structured question UI is unavailable, ask one direct question in the current surface.",
        ("interview_started", "question_asked", "clarity_recorded"),
        "Record a delegated interviewer only when Hermes exposes that lane; otherwise record sequential clarification.",
        "metadata_only",
    ),
    HarnessDefinition(
        "architect",
        "Evaluate system boundaries, integration choices, and long-term maintainability.",
        "Use when a plan touches architecture, runtime integration, extension boundaries, or shared contracts.",
        ("plan", "context", "constraints", "existing architecture evidence"),
        ("architecture verdict", "tradeoff tension", "required changes or clear approval"),
        ("boundary risks are addressed", "chosen approach fits current architecture"),
        ("steelman the strongest antithesis", "check integration claims against evidence"),
        "If delegation is unavailable, run a separate self-review pass before coding.",
        ("architecture_review_started", "tradeoff_recorded", "verdict_recorded"),
        "Record architect delegation only when Hermes exposes an architect lane or wrapper-side role result.",
        "metadata_only",
    ),
    HarnessDefinition(
        "critic",
        "Challenge plan consistency, quality criteria, and missing verification.",
        "Use after planning or before release when a bad assumption would be costly.",
        ("plan", "test spec", "architect review", "user constraints"),
        ("approval or requested changes", "critical findings", "residual risks"),
        ("quality criteria are testable", "risks have mitigations", "alternatives are fair"),
        ("check principle-option consistency", "reject vague acceptance criteria"),
        "If no critic role exists, do a bug-first checklist review and cite concrete evidence.",
        ("critic_review_started", "finding_recorded", "verdict_recorded"),
        "Record critic delegation only when Hermes exposes a critic lane or wrapper-side role result.",
        "metadata_only",
    ),
    HarnessDefinition(
        "qa-specialist",
        "Design adversarial scenarios and verify user-visible behavior before completion.",
        "Use when changes affect workflows, installer behavior, docs examples, or routing claims.",
        ("acceptance criteria", "changed behavior", "fixtures or runnable commands"),
        ("test matrix", "hostile scenarios", "pass/fail evidence"),
        ("critical scenarios pass", "known manual gaps are listed"),
        ("run targeted tests", "cover failure modes and recovery paths"),
        "If runtime automation is unavailable, use fixtures and document manual checks.",
        ("qa_started", "scenario_recorded", "pass_fail_recorded"),
        "Record QA delegation only when Hermes exposes a QA lane or wrapper-side QA result.",
        "metadata_only",
    ),
    HarnessDefinition(
        "docs-specialist",
        "Keep public docs accurate, installable, and aligned with actual behavior.",
        "Use whenever user-facing commands, routing behavior, examples, or release posture change.",
        ("changed behavior", "commands", "limitations", "audience"),
        ("README/docs updates", "examples", "troubleshooting notes"),
        ("docs match behavior", "claims are conservative", "examples are reproducible"),
        ("run public-content scans", "verify commands and file references"),
        "If behavior is not implemented yet, label it as roadmap instead of current capability.",
        ("docs_review_started", "claim_checked", "docs_updated"),
        "Record docs delegation only when Hermes exposes a docs lane or wrapper-side docs result.",
        "metadata_only",
    ),
]


def builtin_definitions() -> list[SkillDefinition]:
    return list(_DEFINITIONS)


def builtin_harnesses() -> list[HarnessDefinition]:
    return list(_HARNESSES)


CORE_SKILLS = [definition.name for definition in _DEFINITIONS]
DESCRIPTIONS = {definition.name: definition.description for definition in _DEFINITIONS}
