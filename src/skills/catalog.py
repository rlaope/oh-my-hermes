from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    triggers: tuple[str, ...]
    use_when: str
    category: str = "workflow"
    phase: str = "general"
    hermes_role: str = "hybrid-guidance"
    handoff_policy: str = "Use Hermes-native guidance directly; prepare a Codex handoff only when the accepted request requires code edits."
    required_inputs: tuple[str, ...] = ("task statement", "available Hermes context")
    expected_outputs: tuple[str, ...] = ("workflow-shaped response", "verification or explicit gap")
    artifact_expectations: tuple[str, ...] = ("metadata-only runtime record when a wrapper or shell is available",)
    safety_rules: tuple[str, ...] = (
        "Do not imply hidden Hermes runtime behavior.",
        "Use the smallest verification that can prove the claim.",
    )


@dataclass(frozen=True)
class HarnessDefinition:
    name: str
    purpose: str
    use_when: str
    required_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    verification: tuple[str, ...]
    fallback: str
    artifact_events: tuple[str, ...]
    delegation_expectation: str
    privacy_default: str


CODING_INTENTS = ("coding", "cleanup", "review", "planning", "diagnostics", "docs", "unknown")
CODING_INTENT_PRIORITY = ("cleanup", "review", "planning", "diagnostics", "docs", "coding")
CODING_INTENT_TERMS = {
    "cleanup": ("cleanup", "clean", "refactor", "deslop"),
    "review": ("review", "audit", "critic", "critique"),
    "planning": ("plan", "planning", "strategy", "architecture", "design", "proposal"),
    "diagnostics": ("diagnose", "doctor", "debug", "health", "broken", "failing"),
    "docs": ("docs", "documentation", "readme", "guide", "wiki"),
    "coding": ("code", "implement", "build", "fix", "change", "modify", "add", "write"),
}
CODING_REVIEW_TERMS = (*CODING_INTENT_TERMS["review"], "risky", "risk", "migration", "security", "public api")
_CODING_INTENT_BY_SKILL = {
    "ai-slop-cleaner": "cleanup",
    "code-review": "review",
    "plan": "planning",
    "ralplan": "planning",
    "best-practice-research": "planning",
    "web-research": "planning",
    "doctor": "diagnostics",
    "wiki": "docs",
}


_DEFINITIONS = [
    SkillDefinition(
        "oh-my-hermes",
        "Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.",
        ("oh-my-hermes", "omh", "skill routing", "workflow routing"),
        "Use as the top-level router when a request references oh-my-hermes, installed workflows, or ambiguous workflow routing.",
        category="router",
        phase="routing",
        hermes_role="retained-router",
        handoff_policy="Classify requests into Hermes-retained planning/research/interview lanes or prepared Codex coding handoffs; do not execute code.",
        required_inputs=("user request", "installed skill descriptions", "Hermes skill discovery context"),
        expected_outputs=("selected workflow guidance", "clarification question when routing is ambiguous"),
        artifact_expectations=("runtime run record when a wrapper can observe request handling",),
        safety_rules=(
            "Prefer explicit skill invocation over weak keyword inference.",
            "Ask one concise question when routing signals conflict.",
            "Do not claim to override Hermes core routing.",
        ),
    ),
    SkillDefinition(
        "ralph",
        "Hermes Ralph workflow: persistent execution with verification and review.",
        ("ralph", "$ralph", "finish until done", "persistent execution", "self-referential loop"),
        "Use after scope is concrete and the user wants one owner to continue through implementation and verification.",
        category="execution",
        phase="completion",
        hermes_role="codex-handoff-guidance",
        handoff_policy="Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track a Codex lifecycle instead of making Hermes the coder.",
        required_inputs=("concrete scope", "acceptance criteria", "verification commands"),
        expected_outputs=("completed work summary", "verification evidence", "remaining risks"),
        artifact_expectations=("goal-execution run record", "checkpoint or final evidence when available"),
    ),
    SkillDefinition(
        "ultragoal",
        "Hermes Ultragoal workflow: file-backed durable goal ledgers.",
        ("ultragoal", "$ultragoal", "durable goal", "multi-goal", "goal ledger"),
        "Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.",
        category="execution",
        phase="durable-goals",
        hermes_role="codex-handoff-guidance",
        handoff_policy="Use Hermes to maintain durable goal/checkpoint state; delegate coding milestones to Codex and report only observed runtime evidence.",
        required_inputs=("goal statement", "acceptance criteria", "current checkpoint"),
        expected_outputs=("goal ledger updates", "checkpoint evidence", "completion or blocker summary"),
        artifact_expectations=("goal ledger or checklist", "runtime run record for each major checkpoint"),
    ),
    SkillDefinition(
        "deep-interview",
        "Hermes Deep Interview workflow: one-question-at-a-time clarification.",
        ("deep-interview", "$deep-interview", "interview", "don't assume", "clarify"),
        "Use before planning or execution when requirements are materially ambiguous.",
        category="clarification",
        phase="discovery",
        hermes_role="retained-cognition",
        handoff_policy="Run directly in Hermes or the chat wrapper; produce a clarified brief before any Codex handoff is prepared.",
        required_inputs=("initial request", "known repo facts", "current ambiguity"),
        expected_outputs=("clarified brief", "non-goals", "decision boundaries"),
        artifact_expectations=("clarity summary or transcript when the wrapper supports it",),
        safety_rules=(
            "Ask one question at a time.",
            "Gather discoverable repo facts before asking the user.",
            "Stop interviewing once ambiguity is low enough to plan.",
        ),
    ),
    SkillDefinition(
        "team",
        "Hermes Team workflow: coordinated parallel or sequential work lanes.",
        ("team", "$team", "swarm", "parallel agents", "coordinated workers"),
        "Use when multiple independent lanes materially improve throughput or verification.",
        category="execution",
        phase="coordination",
        hermes_role="codex-handoff-guidance",
        handoff_policy="Use Hermes for lane framing and status; implementation lanes should become Codex handoff tasks unless they are research, interview, planning, or status-only.",
        required_inputs=("bounded lane definitions", "ownership boundaries", "verification target"),
        expected_outputs=("lane results", "integration summary", "combined verification evidence"),
        artifact_expectations=("delegation record only when separate participants are observed",),
        safety_rules=(
            "Use parallel lanes only when work is independent.",
            "Keep shared-file edits under one owner.",
            "Record unobserved delegation as not_observed.",
        ),
    ),
    SkillDefinition(
        "ultrawork",
        "Hermes Ultrawork compatibility workflow: bounded parallel delivery guidance.",
        ("ultrawork", "$ultrawork", "parallel work", "parallel implementation", "high throughput"),
        "Use when an accepted implementation plan can be split into independent, reviewable work lanes.",
        category="execution",
        phase="parallel-delivery",
        hermes_role="codex-handoff-guidance",
        handoff_policy="Keep the workflow name for compatibility, but convert coding lanes into explicit Codex handoffs with disjoint scope, verification, and review evidence.",
        required_inputs=("accepted plan", "lane list", "disjoint file or responsibility scopes", "verification commands"),
        expected_outputs=("Codex handoff prompts or lane instructions", "status summary", "review/CI evidence requirements"),
        artifact_expectations=("prepared coding delegation record per implementation lane when wrappers can record them",),
        safety_rules=(
            "Do not start parallel coding without disjoint ownership boundaries.",
            "Keep Hermes responsible for orchestration/status, not hidden implementation.",
            "Record unobserved Codex execution as prepared_not_observed or not_observed.",
        ),
    ),
    SkillDefinition(
        "web-research",
        "Hermes Web Research workflow: source-backed current information gathering.",
        ("web-research", "web research", "latest", "current sources", "source-backed research"),
        "Use when the user needs current web evidence, links, citations, or source comparison before planning or handoff.",
        category="research",
        phase="current-evidence",
        hermes_role="retained-cognition",
        handoff_policy="Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.",
        required_inputs=("research question", "source boundaries", "recency or jurisdiction constraints"),
        expected_outputs=("source-backed synthesis", "links or citations", "confidence and residual uncertainty"),
        artifact_expectations=("research notes with source URLs when the wrapper captures them",),
        safety_rules=(
            "Prefer official or primary sources when they can answer the question.",
            "Separate quoted evidence from inference.",
            "State retrieval limits and dates for unstable facts.",
        ),
    ),
    SkillDefinition(
        "ultraqa",
        "Hermes UltraQA workflow: adversarial QA and fix loops.",
        ("ultraqa", "$ultraqa", "adversarial qa", "hostile scenarios", "e2e qa"),
        "Use when the task needs adversarial test scenarios, verification, and fix loops.",
        category="verification",
        phase="qa",
        hermes_role="hybrid-verification",
        handoff_policy="Hermes can design scenarios and report observed results; code fixes discovered by QA should become Codex handoffs.",
        required_inputs=("changed behavior", "acceptance criteria", "known risk areas"),
        expected_outputs=("adversarial scenarios", "pass/fail evidence", "fix recommendations"),
        artifact_expectations=("QA scenario evidence", "runtime verification summary"),
    ),
    SkillDefinition(
        "plan",
        "Hermes Plan workflow: structured planning before execution.",
        ("plan", "$plan", "implementation plan", "strategy", "task breakdown"),
        "Use for structured planning when implementation is not ready to start safely.",
        category="planning",
        phase="plan",
        hermes_role="retained-cognition",
        handoff_policy="Keep planning in Hermes; if the accepted plan requires code edits, prepare a Codex handoff after acceptance.",
        required_inputs=("requirements", "constraints", "known facts", "non-goals"),
        expected_outputs=("plan", "acceptance criteria", "verification strategy"),
        artifact_expectations=("plan artifact when durable execution will follow",),
    ),
    SkillDefinition(
        "ralplan",
        "Hermes Ralplan workflow: consensus planning with review gates.",
        ("ralplan", "$ralplan", "consensus plan", "reviewed plan"),
        "Use when requirements are clear enough for planning but architecture, risks, or tests need review.",
        category="planning",
        phase="reviewed-plan",
        hermes_role="retained-cognition",
        handoff_policy="Keep consensus planning and review in Hermes; produce explicit Codex handoff guidance only after the plan is accepted.",
        required_inputs=("requirements", "options", "tradeoffs", "test shape"),
        expected_outputs=("approved plan", "risk review", "handoff guidance"),
        artifact_expectations=("plan and review artifacts when a wrapper supports file-backed planning",),
        safety_rules=(
            "Do not implement directly from the planning lane.",
            "Make acceptance criteria testable.",
            "Record unresolved tradeoffs explicitly.",
        ),
    ),
    SkillDefinition(
        "code-review",
        "Hermes Code Review workflow: bug-first review with evidence.",
        ("code-review", "$code-review", "review", "audit", "find bugs"),
        "Use for review-shaped requests; findings come first and must cite concrete evidence.",
        category="review",
        phase="critique",
        hermes_role="hybrid-review",
        handoff_policy="Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to Codex.",
        required_inputs=("diff or files", "expected behavior", "test evidence"),
        expected_outputs=("ranked findings", "open questions", "test gaps"),
        artifact_expectations=("critic run record when review evidence is captured",),
        safety_rules=(
            "Findings come before summaries.",
            "Cite concrete evidence for every finding.",
            "Say clearly when no issue is found.",
        ),
    ),
    SkillDefinition(
        "ai-slop-cleaner",
        "Hermes AI slop cleaner workflow: behavior-preserving cleanup.",
        ("ai-slop-cleaner", "$ai-slop-cleaner", "cleanup", "deslop", "refactor"),
        "Use for behavior-preserving cleanup with tests before and after edits.",
        category="maintenance",
        phase="cleanup",
        hermes_role="codex-handoff-guidance",
        handoff_policy="Use Hermes to define cleanup scope and regression checks; delegate behavior-preserving edits to Codex once tests are clear.",
        required_inputs=("target smell", "current behavior", "regression checks"),
        expected_outputs=("small cleanup diff", "before/after verification", "residual risk"),
        artifact_expectations=("cleanup plan and regression evidence for non-trivial work",),
        safety_rules=(
            "Lock behavior with tests before risky cleanup.",
            "Prefer deletion and existing utilities over new layers.",
            "Do not add dependencies for cleanup unless explicitly requested.",
        ),
    ),
    SkillDefinition(
        "best-practice-research",
        "Hermes adaptation for bounded official/upstream best-practice research.",
        ("best-practice-research", "best practice", "official docs", "upstream guidance"),
        "Use when correctness depends on current official or upstream guidance.",
        category="research",
        phase="evidence",
        hermes_role="retained-cognition",
        handoff_policy="Run as Hermes-side evidence gathering; hand coding to Codex only after source-backed guidance is summarized.",
        required_inputs=("chosen technology", "question", "version or environment constraints"),
        expected_outputs=("source-backed guidance", "applicability notes", "residual uncertainty"),
        artifact_expectations=("research notes or citations when the wrapper captures them",),
    ),
    SkillDefinition(
        "autoresearch-goal",
        "Hermes adaptation for durable research-goal execution.",
        ("autoresearch-goal", "research goal", "durable research", "critic research"),
        "Use for validator-gated research that needs durable artifacts.",
        category="research",
        phase="durable-research",
        hermes_role="retained-cognition",
        handoff_policy="Keep durable research in Hermes-managed artifacts; do not convert to Codex unless the research produces an accepted coding task.",
        required_inputs=("research objective", "validator criteria", "source boundaries"),
        expected_outputs=("research artifact", "validator result", "next questions"),
        artifact_expectations=("durable research ledger or checklist",),
    ),
    SkillDefinition(
        "performance-goal",
        "Hermes adaptation for measurable performance-goal execution.",
        ("performance-goal", "performance goal", "latency", "throughput", "benchmark"),
        "Use when the goal is measurable performance improvement with evaluator evidence.",
        category="optimization",
        phase="measurement",
        hermes_role="hybrid-measurement",
        handoff_policy="Hermes can own baselines, benchmark plans, and status; optimization code changes should be Codex handoffs.",
        required_inputs=("metric", "baseline", "budget", "benchmark command"),
        expected_outputs=("measurement delta", "implementation summary", "benchmark evidence"),
        artifact_expectations=("baseline and final benchmark evidence",),
    ),
    SkillDefinition(
        "wiki",
        "Hermes adaptation for maintaining a project-local markdown wiki.",
        ("wiki", "project wiki", "memory", "notes"),
        "Use to capture durable project knowledge in markdown artifacts.",
        category="knowledge",
        phase="capture",
        hermes_role="retained-knowledge",
        handoff_policy="Run directly in Hermes as knowledge capture unless the note reveals a separate coding task.",
        required_inputs=("project fact", "source evidence", "target topic"),
        expected_outputs=("markdown note", "retrieval hint", "staleness warning when needed"),
        artifact_expectations=("repo-local markdown knowledge artifact",),
    ),
    SkillDefinition(
        "ask",
        "Hermes adaptation for consulting an external advisor when configured.",
        ("ask", "$ask", "external advisor", "claude", "gemini"),
        "Use only when an external advisor is configured and would materially improve the answer.",
        category="review",
        phase="external-advice",
        hermes_role="hybrid-review",
        handoff_policy="Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.",
        required_inputs=("question", "context summary", "why external advice helps"),
        expected_outputs=("advisor summary", "accepted/rejected advice", "decision note"),
        artifact_expectations=("advisor transcript reference only when explicitly captured",),
        safety_rules=(
            "Use only when configured and materially useful.",
            "Treat advisor output as evidence to evaluate, not authority.",
            "Do not send secrets or private prompts without explicit opt-in.",
        ),
    ),
    SkillDefinition(
        "cancel",
        "Hermes adaptation for ending active workflow state cleanly.",
        ("cancel", "$cancel", "stop", "abort"),
        "Use to cleanly end active adapted workflow state.",
        category="operator",
        phase="state-cleanup",
        hermes_role="retained-operator",
        handoff_policy="Run directly in Hermes/runtime state; never delegate cancellation to Codex.",
        required_inputs=("active workflow state", "cancellation intent"),
        expected_outputs=("cleared state", "safe stop summary"),
        artifact_expectations=("state clear record when state exists",),
    ),
    SkillDefinition(
        "skill",
        "Hermes adaptation for managing local skills.",
        ("skill", "$skill", "skills", "manage skills"),
        "Use for local skill listing, search, add, remove, or edit tasks.",
        category="operator",
        phase="skill-management",
        hermes_role="retained-operator",
        handoff_policy="Use Hermes for inventory and guidance; delegate only repository code changes to Codex.",
        required_inputs=("skill action", "target skill name or directory"),
        expected_outputs=("skill inventory or mutation result", "verification note"),
        artifact_expectations=("manifest update when managed skills change",),
    ),
    SkillDefinition(
        "doctor",
        "Hermes adaptation for diagnosing oh-my-hermes installation health.",
        ("doctor", "$doctor", "diagnose omh", "installation health"),
        "Use to diagnose OMH installation and Hermes config registration.",
        category="operator",
        phase="diagnostics",
        hermes_role="retained-operator",
        handoff_policy="Run directly as local health inspection; propose Codex work only when a repo fix is required.",
        required_inputs=("omh home", "Hermes home", "observed issue"),
        expected_outputs=("health checks", "fix guidance", "known proof boundary"),
        artifact_expectations=("doctor state summary when runtime artifacts are writable",),
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
        ("run_started", "coding_delegation_recorded", "verification_recorded"),
        "Record prepared coding delegation with omh coding delegate; record observed execution only when Hermes exposes a separate coding, review, or verification lane.",
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
        "research",
        "Gather current or source-backed evidence before planning or coding handoff.",
        "Use when the request needs web/current/official source evidence or source comparison.",
        ("research question", "source boundaries", "recency or environment constraints"),
        ("source-backed synthesis", "links or citations", "confidence and residual uncertainty"),
        ("claims are source-backed", "retrieval limits and dates are explicit"),
        ("prefer official or primary sources", "separate evidence from inference"),
        "If web access is unavailable, state the retrieval gap and fall back to best available local evidence.",
        ("research_started", "source_checked", "synthesis_recorded"),
        "Record a research lane only when Hermes or the wrapper exposes source/research evidence; otherwise summarize retrieval limits explicitly.",
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


_PRIMARY_HARNESSES = {
    "ralph": "goal-execution",
    "ultragoal": "goal-execution",
    "deep-interview": "deep-interview",
    "team": "goal-execution",
    "ultrawork": "goal-execution",
    "web-research": "research",
    "ultraqa": "qa-specialist",
    "plan": "planning",
    "ralplan": "planning",
    "code-review": "critic",
    "ai-slop-cleaner": "coding-handling",
    "best-practice-research": "research",
    "autoresearch-goal": "research",
    "performance-goal": "goal-execution",
    "wiki": "docs-specialist",
    "ask": "critic",
    "cancel": "goal-execution",
    "skill": "docs-specialist",
    "doctor": "qa-specialist",
}


def builtin_definitions() -> list[SkillDefinition]:
    return list(_DEFINITIONS)


def builtin_harnesses() -> list[HarnessDefinition]:
    return list(_HARNESSES)


def primary_harness_for_skill(name: str) -> str:
    return _PRIMARY_HARNESSES.get(name, "coding-handling")


def coding_intent_for_skill(name: str) -> str:
    return _CODING_INTENT_BY_SKILL.get(name, "coding")


def coding_skills_for_intent(intent: str) -> tuple[str, ...]:
    return tuple(name for name, mapped_intent in _CODING_INTENT_BY_SKILL.items() if mapped_intent == intent)


def coding_terms_for_intent(intent: str) -> tuple[str, ...]:
    return CODING_INTENT_TERMS.get(intent, ())


CORE_SKILLS = [definition.name for definition in _DEFINITIONS]
DESCRIPTIONS = {definition.name: definition.description for definition in _DEFINITIONS}
