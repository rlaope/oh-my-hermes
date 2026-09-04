"""Types, defaults, and naming rules every catalog table is built from.

Split out of `catalog.py` so a reader meets the contract before the data. Nothing
here knows which skills exist; it defines what a skill *is* - the dataclasses, the
role and checklist defaults `SkillDefinition.__post_init__` fills in, the
`omh-`/`ulw-` display rule, and the coding-intent vocabulary.

The data tables live in `catalog_definitions`, `catalog_feature_surfaces`, and
`catalog_harnesses`; `catalog.py` assembles them and owns the public accessors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..workflows.operations_contracts import ArtifactContractRef, artifact_contracts_for_workflow


OMH_DESCRIPTION_PREFIX = "[omh] "


def omh_description(description: str) -> str:
    text = description.strip()
    if text.lower().startswith(OMH_DESCRIPTION_PREFIX):
        return text
    return f"{OMH_DESCRIPTION_PREFIX}{text}"


OMH_SKILL_NAME_PREFIX = "omh-"

# Canonical catalog names that get a hand-picked display label instead of the
# mechanical prefix. The override lookup runs before the idempotency guard in
# omh_skill_display_name() because that guard tests the INPUT name, not the
# override value: the two orders diverge only for an override KEY that already
# starts with `omh-`, which a prefix-first implementation would short-circuit
# before ever reaching its override. No current key does, so the ordering is a
# forward-looking contract rather than a live behavior.
OMH_SKILL_DISPLAY_NAME_OVERRIDES = {
    "oh-my-hermes": "omh-routing",
    # `product-docs` avoids reserving the generic canonical word `docs` while
    # preserving the public skill name requested by users.
    "product-docs": "omh-docs",
    # `strategy-brief` says what the output is, not what the skill does for
    # you. The skill turns goals and evidence into options, tradeoffs, and a
    # recommendation - it helps you decide. The canonical name stays put
    # (directory, manifest, tap URL, triggers); only the label a reader sees
    # changes.
    "strategy-brief": "omh-decide",
    # `ulw` already carries the "ultra". `ulw-ultrawork` says it twice, and the
    # duplicated syllable is the part a reader has to skip past to reach the
    # word that means something. Canonical names are untouched.
    "context": "ulw-context",
    "deep-interview": "ulw-interview",
    "ralplan": "ulw-plan",
    "ultragoal": "ulw-goal",
    "ultraprocess": "ulw-process",
    "ultraqa": "ulw-qa",
    "ultrawork": "ulw-work",
    # `ulw-performance` spells the domain out; `ulw-perf` is the label an
    # operator actually scans for in a status line, and the engine family
    # already abbreviates (`ulw-plan`, `ulw-qa`). Canonical name stays put.
    "ultraperf": "ulw-perf",
    # The `-operator` suffix names the implementation pattern, not the job. A
    # reader scanning a picker wants the job: the browser one drives web pages,
    # the terminal one scopes shell commands, the apps one reaches email/Slack/
    # Notion-style providers. Two labels also correct outright misreads:
    # `voice-operator` shapes terse voice/mobile-style REQUESTS (it does not
    # speak), and `img-summary` GENERATES image prompt cards (it does not
    # summarize images). Canonical names stay put everywhere, and the old
    # `omh-<canonical>` labels keep routing as historical aliases.
    "browser-operator": "omh-browser",
    "workspace-file-operator": "omh-files",
    "command-operator": "omh-terminal",
    "connector-operator": "omh-apps",
    "live-info-operator": "omh-live-info",
    "media-input-operator": "omh-media-input",
    "voice-operator": "omh-voice-input",
    "img-summary": "omh-image-cards",
}

ULW_SKILL_NAME_PREFIX = "ulw-"

# The workflow-engine skills: the ones that drive a run rather than do a domain
# job. A user reaching for `ultrawork` wants an execution engine pointed at
# whatever they are already doing; a user reaching for `content-operator` wants
# that specific job done. The two read differently in a status line, so they get
# different labels.
#
# Membership is enumerated rather than derived from `category`, because the
# members span execution, clarification, research, planning, optimization, and
# verification -
# the grouping is what the skill is FOR, not where it sits in the catalog. Keep
# it small and explicit: a domain skill that drifts in here would make the
# distinction meaningless, which is the only thing the split is buying.
ULW_ENGINE_SKILL_NAMES = frozenset(
    {
        "context",
        "deep-interview",
        "loop",
        "maestro",
        "ralph",
        "ralplan",
        "research",
        "team",
        "ultragoal",
        "ultraprocess",
        "ultraperf",
        "ultraqa",
        "ultrawork",
    }
)


def omh_skill_display_name(name: str) -> str:
    """Return the rendered frontmatter label for a canonical catalog name.

    This is a display identifier that, since the relabel, also names the
    `skills/<label>/` install directory. The canonical `SkillDefinition.name`
    still owns the install manifest `name`, routing keys, and every CLI
    argument.
    """
    text = name.strip()
    override = OMH_SKILL_DISPLAY_NAME_OVERRIDES.get(text)
    if override is not None:
        return override
    prefix = ULW_SKILL_NAME_PREFIX if text in ULW_ENGINE_SKILL_NAMES else OMH_SKILL_NAME_PREFIX
    if text.startswith(prefix):
        return text
    return f"{prefix}{text}"


def historical_skill_display_names(name: str) -> tuple[str, ...]:
    """Return display labels earlier releases rendered for this canonical name.

    Two label eras shipped before the current one: `omh-<name>` for every
    skill, then `ulw-<name>` for the workflow engines before their labels were
    shortened (`ulw-ultrawork` → `ulw-work`). Stale agents, memories, and docs
    still echo those forms, so routing accepts them as aliases of the current
    label instead of letting them silently miss. Current labels always win a
    collision; a rename here is deliberately additive.
    """
    text = name.strip()
    current = omh_skill_display_name(text)
    candidates = [f"{OMH_SKILL_NAME_PREFIX}{text}"]
    if text in ULW_ENGINE_SKILL_NAMES:
        candidates.append(f"{ULW_SKILL_NAME_PREFIX}{text}")
    return tuple(candidate for candidate in candidates if candidate != current)


_ROLE_BY_CATEGORY = {
    "accessibility": "guide",
    "agent-coordination": "tracker",
    "clarification": "planner",
    "deliverables": "operator",
    "delivery": "operator",
    "execution": "handoff-guide",
    "executor-readiness": "handoff-guide",
    "gateway": "guide",
    "github-ops": "operator",
    "goal-loop": "planner",
    "knowledge": "memory-keeper",
    "leadership": "operator",
    "maintenance": "handoff-guide",
    "materials": "operator",
    "meeting": "operator",
    "memory": "memory-keeper",
    "monitoring": "operator",
    "observability": "tracker",
    "operations": "operator",
    "operator": "tracker",
    "optimization": "tracker",
    "planning": "planner",
    "process": "handoff-guide",
    "reliability": "operator",
    "reporting": "operator",
    "research": "researcher",
    "review": "reviewer",
    "router": "guide",
    "strategy": "operator",
    "tools": "tracker",
    "triage": "operator",
    "verification": "reviewer",
}

REASONING_DEMAND_VALUES = ("light", "standard", "heavy")

# Per-skill demand stays executor-neutral. Empty catalog entries inherit their
# category's conservative default so only genuine cross-category outliers need
# to declare a value.
_REASONING_DEMAND_BY_CATEGORY = {
    "accessibility": "light",
    "clarification": "light",
    "executor-readiness": "light",
    "gateway": "light",
    "hermes-setup": "light",
    "knowledge": "light",
    "meeting": "light",
    "memory": "light",
    "monitoring": "light",
    "operations": "light",
    "operator": "light",
    "router": "light",
    "deliverables": "standard",
    "materials": "standard",
    "observability": "standard",
    "planning": "standard",
    "reporting": "standard",
    "reliability": "standard",
    "research": "standard",
    "review": "standard",
    "strategy": "standard",
    "triage": "standard",
    "verification": "standard",
    "delivery": "heavy",
    "execution": "heavy",
    "goal-loop": "heavy",
    "leadership": "heavy",
    "maintenance": "heavy",
    "optimization": "heavy",
    "process": "heavy",
}


_ROLE_ALIASES = {
    "coding-handoff": "handoff-guide",
    "codex-handoff-guidance": "handoff-guide",
    "hybrid-guidance": "guide",
    "hybrid-measurement": "tracker",
    "hybrid-review": "reviewer",
    "hybrid-verification": "reviewer",
    "planning-lead": "planner",
    "research-lead": "researcher",
    "retained-cognition": "",
    "retained-knowledge": "memory-keeper",
    "retained-operator": "",
    "review-gate": "reviewer",
    "retained-router": "guide",
    "runtime-handoff-guidance": "handoff-guide",
}


def canonical_hermes_role(name: str, category: str, requested: str) -> str:
    """Return the user-facing OMH responsibility role for a skill."""
    if requested in _ROLE_ALIASES and _ROLE_ALIASES[requested]:
        return _ROLE_ALIASES[requested]
    if category in _ROLE_BY_CATEGORY:
        return _ROLE_BY_CATEGORY[category]
    if requested in _ROLE_ALIASES:
        return "guide"
    return requested or "guide"


_GENERAL_FINAL_CHECKLIST = (
    "Confirm the workflow target, evidence boundary, and stop condition are named.",
    "Report which outputs are prepared, observed, blocked, or missing.",
    "Name the smallest next verification or handoff instead of claiming completion from narration.",
)

_GENERAL_RECOVERY_NOTES = (
    "If required context is missing, ask one blocking question or route back to the narrower workflow.",
    "If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.",
)

_HANDOFF_FINAL_CHECKLIST = (
    "The selected coding or runtime owner is named before any implementation claim.",
    "Prepared handoff, dispatch, execution, verification, review, CI, and merge states are separated.",
    "The final status cites observed runtime evidence or keeps the work prepared_not_observed.",
)

_HERMES_CODING_HARNESS_FINAL_CHECKLIST = (
    "When Hermes is the selected coding owner, use `hermes_coding_harness/v1` to keep builder, verifier, reviewer, docs, and PR lanes separate.",
    "Report the current harness stage, owner, next action, and missing evidence without claiming PR creation, review, CI, merge-readiness, or merge until matching runtime observations exist.",
)

# maestro cannot reuse the generic Hermes-owner harness line above: its own
# safety rule ("Never route a Hermes-owned lane through this engine") and its
# facade's HermesNativeSelectionError mean the engine structurally cannot have
# Hermes as the selected owner, so `hermes_coding_harness/v1` guidance never
# applies here. This is the one honest replacement line for maestro's own
# `final_checklist` override -- see its `SkillDefinition` in
# catalog_definitions.py.
_MAESTRO_HERMES_OWNER_FINAL_CHECKLIST_NOTE = (
    "When Hermes is the selected coding owner this engine does not apply -- Hermes-native selection uses the "
    "Hermes runtime path, never this engine."
)

# The lifecycle bridge maestro's own dispatch semantics leave open: dispatch
# ends at spawn/exit and never merges (docs/FANOUT.md, `DISPATCH_CLAIM_BOUNDARY`
# in `fanout_dispatch.py`), but a unit finishing is not the end of the story.
# `references/executor-prompt-composition.md` (Result Integration) carries the
# full collect/verify/merge/report procedure; this is the always-loaded
# pointer so an agent reading only SKILL.md still knows the bridge exists.
_MAESTRO_RESULT_INTEGRATION_FINAL_CHECKLIST_NOTE = (
    "Dispatch never merges: collect each unit's fanout_unit_result/v1 evidence, verify the integrated combination "
    "of units (not just each one alone -- disjoint file scopes can still conflict at integration), and report "
    "merged/unmerged per unit in the closing brief. Merging the unit branches remains an explicit operator or "
    "reviewing-agent action; a dispatch receipt is never merge evidence."
)

_HANDOFF_RECOVERY_NOTES = (
    "If the selected executor is unavailable, ask for Codex, Claude Code, Hermes, or another runtime before retrying.",
    "If dispatch or result evidence is missing, keep the handoff prepared_not_observed and expose the next observable action.",
)

# Delegation transparency: what the user must be able to see about every
# delegated lane. One maintained copy: the coding-handling harness contract
# composes these rules into its quality bar, and `render.py` renders them into
# every handoff-guide skill body plus the shared common rail, so the discipline
# reaches agents that only ever read `SKILL.md`.
DELEGATE_PROMPT_DISPLAY_RULE = (
    "When delegating, show the composed delegate prompt in a fenced code block in the status message; "
    "truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]` — the user "
    "must see WHAT was asked, not just that something was."
)
DELEGATE_MODEL_LABEL_RULE = (
    "Name every delegated or parallel lane's model and, when the host exposes it, its reasoning effort "
    "inline as `(model effort)` in status and briefing lines — including runtime-native subagents; when "
    "no effort is exposed, show the model alone as `(model)` rather than writing a placeholder like "
    "`unknown` beside a known model, and never emit empty parentheses. Carry token and elapsed figures "
    "the same way in these narration lines: report observed figures and omit unobserved ones — when the "
    "user asks for a figure directly, say it was not observed instead of omitting it; a rendered "
    "status-board column keeps its own `unknown` cell."
)
DELEGATE_RESUMABLE_SESSION_RULE = (
    "Capture a resumable session or thread id at dispatch and report it in the status message: for "
    "non-interactive Claude Code pass `--output-format json` and read `session_id` from the result "
    "(resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` "
    "(resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git "
    "repo). Never leave a delegate run with no recorded way to resume or steer it — a plain-text "
    "one-shot that hides its session id strands the work when the run stalls or times out."
)
DELEGATE_PERMISSION_PREFLIGHT_RULE = (
    "Before dispatch, grant the executor session every permission the task will need — file write/edit, "
    "command/test execution, and the working directory — on the dispatch command itself, not through "
    "settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an "
    "explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or "
    "sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a "
    "settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is "
    "`~/.claude/settings.json` and project scope is `<dispatch cwd>/.claude/settings.local.json` with "
    "rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the "
    "real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never "
    "redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker "
    "before dispatch, not after minutes of silence."
)
DELEGATION_TRANSPARENCY_RULES = (
    DELEGATE_PROMPT_DISPLAY_RULE,
    DELEGATE_MODEL_LABEL_RULE,
    DELEGATE_RESUMABLE_SESSION_RULE,
    DELEGATE_PERMISSION_PREFLIGHT_RULE,
)

# Follow-on engine gate: finishing one workflow (an accepted plan, a clarified
# brief, a routing recommendation) is planning evidence, never permission to
# start the next engine. Planning-lane skills compose the fit-recommendation
# rule; workflow engines compose the entry-confirmation rule into their quality
# bars so a chained start still stops for the user's go-ahead.
ENGINE_FIT_RECOMMENDATION_RULE = (
    "Plan acceptance approves the plan content, not execution: after acceptance, recommend the follow-on "
    "path that fits the work's shape — `ultrawork` durable checkpoints for progress that must survive "
    "sessions as a checkpointed ledger, `ultrawork` coordinated lanes for an accepted plan split into "
    "disjoint parallel lanes, `ultrawork` single-owner persistence for one already-scoped task with a "
    "single owner, `ultrawork` for one bounded delivery cycle, or "
    "a direct selected executor/runtime handoff for a single prepared coding change — state the fit "
    "reason in one line, and start it only after the user's explicit go-ahead."
)
ENGINE_ENTRY_CONFIRMATION_RULE = (
    "Do not start this engine as an automatic continuation of another skill's output: an accepted plan, "
    "a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user "
    "explicitly invoked this engine themselves, restate in one line what will start (engine, scope, "
    "selected executor) and wait for the user's explicit go-ahead first."
)

# Mid-run continuation gate (#1033): a user message arriving during an engine
# run must not end the run. The host already makes resumption possible —
# delegate_task children are async and each result re-enters as a fresh turn —
# so the only thing that can drop the orchestration thread is the model ending
# its reply after answering. Composed into every executing ULW engine's quality
# bar; planning lanes (ralplan, plan, deep-interview) are conversational by
# design and deliberately do not carry it.
ENGINE_INTERJECTION_RESUME_RULE = (
    "A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, "
    "continue the run — re-read the phase todo when one is active and dispatch or advance the next "
    "pending step, or state exactly what the run is waiting on (for example, lanes still in flight that "
    "resume when their results return). Only the user's explicit stop or cancel, or the engine's own "
    "completion gate, ends the run; when the interjection changes scope, say so and update the declared "
    "plan or todo instead of silently abandoning it."
)

# Shared five-step contract for the Hermes setup-guide skills (model-setup,
# parallel-tools, websearch-setup, morning-brief). Ordering is guaranteed by
# tuple index: prerequisite check -> read-only diagnose -> guide -> diff-
# approved apply -> verify. Composed into each skill's quality_bar so the
# rendered SKILL.md carries the items verbatim in index order.
_HERMES_SETUP_FIVE_STEP_BAR = (
    "Prerequisite check: confirm the subscription, account, or capability the step needs exists before continuing; mark unmet prerequisites \"not applicable\" and skip them explicitly.",
    "Read-only diagnose: read the current Hermes config, `.env` keys, and installed version without writing anything.",
    "Guide: walk the user through any account creation, OAuth, or token issuance they must complete themselves.",
    "Diff-approved apply: show the exact config or `.env` diff and write only after the user explicitly approves it.",
    "Verify: re-read the updated config and report a completion checklist covering every applicable item.",
)

_HERMES_SETUP_SKIP_SEMANTICS = (
    "If a prerequisite is unmet, mark that item \"not applicable\" and continue with the rest of the guide instead of blocking or guessing.",
    "Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.",
)

_HERMES_SETUP_WRITE_BOUNDARY = (
    "Diagnosis only reads the existing Hermes config, `.env` keys, and installed version; it never writes anything on its own.",
    "Show the exact diff for any config or `.env` change and write it only after the user explicitly approves that diff.",
    "Secret values such as tokens and API keys are pasted by the user directly in chat and are never stored, logged, or echoed back beyond the immediate diff confirmation.",
)

_CATEGORY_FINAL_CHECKLISTS = {
    "accessibility": (
        "The short-input or voice-like request is clarified enough to avoid accidental action.",
        "The next action is readable, reversible when possible, and confirmation-gated when risky.",
        "Delivery, notification, or platform behavior is not claimed without wrapper evidence.",
    ),
    "clarification": (
        "The clarified brief names goals, non-goals, constraints, and one next planning or handoff path.",
        "Remaining ambiguity is listed only when it changes the plan, risk, or stop condition.",
        "No implementation handoff is prepared until the blocking decision is resolved.",
    ),
    "deliverables": (
        "The deliverable type, audience, source inputs, QA ladder, and delivery boundary are named.",
        "Prepared generation, generated file, render QA, approval, attachment, and delivery are separate states.",
        "The next action says whether to generate, revise, QA, approve, attach, or deliver.",
    ),
    "gateway": (
        "The origin platform, thread/session boundary, delivery target, and update policy are named.",
        "Prepared card or command output is separate from platform registration, send, attachment, or delivery evidence.",
        "The next wrapper action is explicit and platform-safe.",
    ),
    "knowledge": (
        "The durable fact, source evidence, retrieval hint, and staleness risk are recorded.",
        "Uncertain or conflicting knowledge is marked as review-needed rather than permanent truth.",
        "Separate coding or docs tasks are extracted instead of buried in notes.",
    ),
    "materials": (
        "The material source, target format, audience, structure, and QA expectation are named.",
        "Binary export, rendering, formula recalculation, attachment, and delivery stay observed-only.",
        "The next action identifies whether the package is planned, generated, QA-ready, or blocked.",
    ),
    "meeting": (
        "The agenda, participants or audience, decisions needed, and record template are named.",
        "Meeting prep, observed minutes, accepted decisions, and action ownership are separate states.",
        "Missing context that would change the meeting structure is surfaced.",
    ),
    "observability": (
        "The run or workflow scope, metric window, failure modes, and cost/latency boundary are named.",
        "Local telemetry, provider truth, billing truth, and completion evidence are separate states.",
        "Warnings name the next measurement or operator review action.",
    ),
    "operator": (
        "The local command, managed path, config surface, and state artifact inspected are named.",
        "Blocking issues, warnings, and optional surfaces are separated.",
        "The next repair action is explicit and does not claim a reload or runtime observation.",
    ),
    "planning": (
        "The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.",
        "Draft recommendations, accepted decisions, and executor handoffs are separate states.",
        "Rejected options or unresolved tradeoffs are recorded before handoff.",
    ),
    "reporting": (
        "The reporting window, inputs, audience, narrative, and evidence gaps are named.",
        "Draft report, generated package, approval, and delivery are separate states.",
        "The next action says whether to gather evidence, generate, revise, approve, or deliver.",
    ),
    "research": (
        "The research question, source boundaries, recency assumptions, and confidence level are named.",
        "Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.",
        "Follow-up planning or handoff uses the research summary without calling it execution evidence.",
    ),
    "review": (
        "Findings or no-issue results are grounded in concrete file, artifact, command, or source evidence.",
        "Open questions, residual risk, and missing verification are named.",
        "Fixes or follow-up work are separate handoffs unless the user explicitly asked to implement them.",
    ),
    "router": (
        "The selected workflow, confidence reason, evidence boundary, and user-facing next action are named.",
        "Low-confidence or conflicting signals return a picker or clarification instead of forced routing.",
        "Catalog answers are rendered without shell approval when wrapper metadata is sufficient.",
    ),
    "strategy": (
        "The decision, options, tradeoffs, assumptions, and rejected alternatives are named.",
        "Observed signals are separated from strategic inference.",
        "Accepted decisions and implementation follow-ups are not conflated.",
    ),
    "triage": (
        "The source boundary, signal clusters, severity, and follow-up lane are named.",
        "Bug, feature, research, strategy, and coding handoff outcomes stay separate.",
        "The next workflow is recommended before any implementation claim.",
    ),
    "verification": (
        "The scenario, expected behavior, observed result, and pass/fail basis are named.",
        "Proposed fixes are separated from observed QA evidence.",
        "Missing or failed verification routes back to plan, fix, or a narrower test.",
    ),
}

# Deep-interview round bounds. Single source of truth for every surface that states
# the budget: the rendered skill protocol block, the catalog safety rule and recovery
# note, the deep_interview_contract/v1 payload, the wrapper clarification ack, and the
# harness stop condition. Never restate these numbers as literals or spelled-out
# ordinals; interpolate them so one edit moves every surface together.
DEEP_INTERVIEW_MAX_ROUNDS = 6
DEEP_INTERVIEW_SOFT_CHECK_ROUND = 4
DEEP_INTERVIEW_CLARITY_DIMENSIONS = (
    "outcome",
    "constraints and non-goals",
    "success criteria",
)

# Adversarial-consensus vocabulary. Single source of truth for every surface
# that states the perspective bounds, the round order, or the distillation
# buckets: the catalog quality bar and final checklist, and the rendered
# `references/consensus-protocol.md`. Never restate these as literals or
# spelled-out ordinals; interpolate them so one edit moves every surface
# together.
ADVERSARIAL_CONSENSUS_MIN_PERSPECTIVES = 3
ADVERSARIAL_CONSENSUS_MAX_PERSPECTIVES = 5
# The suggested roster, not a closed set: a perspective earns its seat by
# attacking the problem from an angle no other seat covers, so a domain-specific
# substitution is expected and a duplicate angle is the real defect.
ADVERSARIAL_CONSENSUS_PERSPECTIVES = (
    "skeptic",
    "validator",
    "researcher",
    "architect",
    "creative",
)
# Ordered, and the order is the contract: independence is only real before any
# perspective has read another's findings, and an attack round that runs after
# a defense round is just agreement with extra steps.
ADVERSARIAL_CONSENSUS_ROUNDS = (
    "independent findings",
    "cross-attack",
    "defend, refine, or concede",
)
# Closed set. The distillation writes into these four buckets and nothing else;
# a fifth bucket is how a distillation quietly becomes the plan it must not be.
ADVERSARIAL_CONSENSUS_BUCKETS = (
    "Hard Constraints",
    "Decisions",
    "Risks",
    "Open Questions",
)

# llm-app-dev vocabulary. Single source of truth for every surface that names
# the build rails or the eval deliverables: the catalog quality bar and final
# checklist, and the rendered `references/build-rails.md` and
# `references/eval-harness.md`. Interpolate rather than retype, so the
# always-loaded body and the on-demand references cannot drift into two
# different disciplines.
#
# Ordered by when getting it wrong becomes expensive to undo: a provider
# boundary chosen late means rewriting every call site, while an eval suite
# added late only means not knowing whether the last swap helped.
LLM_APP_DEV_RAILS = (
    "provider boundary",
    "structured output",
    "prompt artifacts",
    "retrieval grounding",
    "evaluation",
)
# The eval deliverables that make a prompt or model swap reviewable. Named as
# artifacts, not activities: "we evaluated it" is not a deliverable, a golden
# set committed next to the code is.
LLM_APP_DEV_EVAL_DELIVERABLES = (
    "golden set",
    "task-level validators",
    "baseline-vs-candidate comparison",
)

DECISION_FRONTIER_POLICY_SCHEMA_VERSION = "decision_frontier_policy/v1"
DECISION_FRONTIER_HARNESS = "decision-frontier"
DECISION_FRONTIER_BUDGET_SCOPE = "clarification_episode"
DECISION_FRONTIER_ROUND_UNIT = "dependency_ready_batch"
DECISION_FRONTIER_DECISION_ID_PREFIX = "D"
DECISION_FRONTIER_DECISION_STATES = (
    "open",
    "resolved",
    "deferred",
    "blocked",
)
DECISION_FRONTIER_STOP_RULE_ORDER = (
    "frontier_terminal",
    "user_stop",
    "round_ceiling",
)
DECISION_FRONTIER_PARTIAL_ANSWER_POLICY = "addressed_only"
DECISION_FRONTIER_OMITTED_ANSWER_TRANSITION = "none"
DECISION_FRONTIER_RECOMMENDATION_POLICY = "explicit_acceptance_only"
DECISION_FRONTIER_USER_STOP_SCOPE = "questioning_only"
DECISION_FRONTIER_COMPACTION_FAILURE_ACTION = "close_with_recovery_blocker"
DECISION_FRONTIER_CONSENT_GATES = (
    "frontier_entry",
    "summary_confirmation",
    "next_path",
)

_CATEGORY_RECOVERY_NOTES = {
    "accessibility": (
        "If transcript confidence or intent is weak, ask one short clarification before action.",
        "If platform delivery is unavailable, keep the response in chat and mark delivery not_observed.",
    ),
    "clarification": (
        "If the user answers with new ambiguity, ask the next decision-changing question instead of planning too early.",
        "If repo evidence can answer the question, inspect it before asking the user.",
    ),
    "deliverables": (
        "If generation tooling is missing, prepare a prompt or package handoff and mark file output not_observed.",
        "If QA or attachment evidence is missing, keep generated/delivered states separate and show the next check.",
    ),
    "gateway": (
        "If platform metadata is missing, keep the card platform-neutral and ask for the target surface.",
        "If send or registration evidence is unavailable, show the adapter-owned action instead of claiming delivery.",
    ),
    "knowledge": (
        "If source evidence conflicts, route to memory or knowledge review before writing durable guidance.",
        "If the fact may be stale, record the staleness warning and next refresh action.",
    ),
    "materials": (
        "If a renderer or file tool is missing, keep the package prepared and expose the generation handoff.",
        "If render QA is unavailable, mark the artifact unverified and request the smallest visual/file check.",
    ),
    "meeting": (
        "If participants, purpose, or decision owner are missing, ask for the one field that changes the agenda.",
        "If minutes or decisions were not observed, keep the output as prep rather than record.",
    ),
    "observability": (
        "If provider metrics are unavailable, report only local metadata and mark provider truth not_observed.",
        "If cost or latency looks risky, surface a warning plus the next measurement rather than a completion claim.",
    ),
    "operator": (
        "If a managed path or config key is missing, route to setup/update repair instead of editing hidden state.",
        "If a reload or plugin load was not observed, keep the diagnostic result as local health evidence only.",
    ),
    "planning": (
        "If acceptance criteria or verification are missing, route back to clarification before handoff.",
        "If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.",
    ),
    "reporting": (
        "If input evidence is incomplete, mark the section as pending rather than fabricating a report claim.",
        "If delivery or attachment is unavailable, keep the report package prepared_not_observed.",
    ),
    "research": (
        "If sources cannot be accessed, state the retrieval gap and use only observed local context.",
        "If evidence is thin or one-sided, lower confidence and ask for a narrower source boundary.",
    ),
    "review": (
        "If the reviewed target is missing, inspect the requested artifact or ask one target question.",
        "If independent verification is unavailable, report the gap and avoid an approval-style claim.",
    ),
    "router": (
        "If routing signals conflict, show the compact picker or ask one clarifying question.",
        "If wrapper metadata is unavailable, keep the recommendation advisory and avoid runtime claims.",
    ),
    "strategy": (
        "If evidence is mostly assumption, label it and recommend a research or feedback-triage pass.",
        "If the decision owner is missing, keep the output as options rather than accepted strategy.",
    ),
    "triage": (
        "If feedback lacks source or severity, ask for the missing signal before coding handoff.",
        "If the item is actually a plan or research request, route to that workflow instead of triage.",
    ),
    "verification": (
        "If the expected behavior is unclear, route back to plan before running adversarial checks.",
        "If verification fails, return to fix or research with the failed signal instead of advancing.",
    ),
}


def _default_final_checklist(name: str, category: str, hermes_role: str, quality_tier: str) -> tuple[str, ...]:
    if hermes_role == "handoff-guide" or quality_tier == "handoff-gated":
        return _HANDOFF_FINAL_CHECKLIST + _HERMES_CODING_HARNESS_FINAL_CHECKLIST
    return _CATEGORY_FINAL_CHECKLISTS.get(category, _GENERAL_FINAL_CHECKLIST)


def _default_recovery_notes(name: str, category: str, hermes_role: str, quality_tier: str) -> tuple[str, ...]:
    if hermes_role == "handoff-guide" or quality_tier == "handoff-gated":
        return _HANDOFF_RECOVERY_NOTES
    return _CATEGORY_RECOVERY_NOTES.get(category, _GENERAL_RECOVERY_NOTES)


@dataclass(frozen=True)
class SkillExample:
    prompt: str
    expected: str
    why: str


@dataclass(frozen=True)
class ExpertQuestion:
    required_input: str
    en: str
    ko: str

    def question_for_locale(self, locale: str) -> str:
        """Return the Korean question only for Korean; otherwise use English."""
        return self.ko if isinstance(locale, str) and locale.casefold() == "ko" else self.en


@dataclass(frozen=True)
class ProcedureCheck:
    check_id: str
    required_result_fields: tuple[str, ...]
    instruction: str


@dataclass(frozen=True)
class ProcedureStep:
    step_id: str
    kind: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    check_ids: tuple[str, ...]
    instruction: str


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    triggers: tuple[str, ...]
    use_when: str
    category: str = "workflow"
    phase: str = "general"
    hermes_role: str = "hybrid-guidance"
    delegation_boundary: str = "default"
    handoff_policy: str = "Use Hermes-native guidance directly; prepare a selected executor/runtime handoff only when the accepted request requires code edits."
    required_inputs: tuple[str, ...] = ("task statement", "available Hermes context")
    expected_outputs: tuple[str, ...] = ("workflow-shaped response", "verification or explicit gap")
    artifact_expectations: tuple[str, ...] = ("metadata-only runtime record when a wrapper or shell is available",)
    safety_rules: tuple[str, ...] = (
        "Do not imply hidden Hermes runtime behavior.",
        "Use the smallest verification that can prove the claim.",
    )
    quality_tier: str = "evidence-gated"
    quality_bar: tuple[str, ...] = (
        "Name the workflow target, constraints, validation evidence, and stop condition.",
        "Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.",
    )
    why_this_exists: str = ""
    do_not_use_when: tuple[str, ...] = ()
    good_example: SkillExample | None = None
    bad_example: SkillExample | None = None
    final_checklist: tuple[str, ...] = ()
    recovery_notes: tuple[str, ...] = ()
    # Render-invisible routing metadata: only consumed by the capability-family
    # projection. Set it only when the skill's family differs from its
    # awareness-lane default; leave empty to inherit the lane default.
    capability_family: str = ""
    # Empty means inherit the category default. The resolved value is exposed
    # as catalog metadata for hosts to apply to their own model inventory.
    reasoning_demand: Literal["light", "standard", "heavy", ""] = ""
    # Short routing-equivalent names surfaced through the frontmatter
    # description because the host picker reads only `name` + `description`.
    aliases: tuple[str, ...] = ()
    # Catalog-owned clarification wording. The ordered first row is the stable
    # high-value question; consumers do not infer that its input is missing.
    expert_questions: tuple[ExpertQuestion, ...] = ()
    # Machine enforcement is independent of the evidence state on produced
    # artifacts. Operations workflows receive their single registry-owned ref.
    artifact_contracts: tuple[ArtifactContractRef, ...] = ()
    # Procedures are opt-in machine contracts. Input and output refs resolve
    # against this definition; check IDs resolve against procedure_checks.
    procedure_checks: tuple[ProcedureCheck, ...] = ()
    procedure_steps: tuple[ProcedureStep, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "description", omh_description(self.description))
        object.__setattr__(self, "hermes_role", canonical_hermes_role(self.name, self.category, self.hermes_role))
        registered_contracts = artifact_contracts_for_workflow(self.name)
        if self.artifact_contracts and registered_contracts != self.artifact_contracts:
            raise ValueError(f"artifact contracts for {self.name} must come from the operations registry")
        if registered_contracts:
            object.__setattr__(self, "artifact_contracts", registered_contracts)
        if self.reasoning_demand == "":
            object.__setattr__(
                self,
                "reasoning_demand",
                _REASONING_DEMAND_BY_CATEGORY.get(self.category, "standard"),
            )
        routing_hint = self.triggers[0] if self.triggers else self.name
        if not self.why_this_exists:
            object.__setattr__(
                self,
                "why_this_exists",
                (
                    f"`{self.name}` exists to keep `{self.category}` work explicit, evidence-backed, "
                    "and inside the Hermes/executor boundary instead of relying on ad hoc chat narration."
                ),
            )
        if not self.do_not_use_when:
            object.__setattr__(
                self,
                "do_not_use_when",
                (
                    "The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.",
                    "The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.",
                ),
            )
        if self.good_example is None:
            default_good_example = _DEFAULT_GOOD_EXAMPLES.get(self.name)
            object.__setattr__(
                self,
                "good_example",
                default_good_example
                or SkillExample(
                    prompt=(
                        f"{routing_hint}: handle a {self.category} request that needs "
                        "explicit evidence boundaries and a clear stop condition."
                    ),
                    expected=f"Run `{self.name}` only after naming the target, evidence boundary, and stop condition.",
                    why="The request matches the catalog use case and keeps observed evidence separate from prepared guidance.",
                ),
            )
        if self.bad_example is None:
            object.__setattr__(
                self,
                "bad_example",
                SkillExample(
                    prompt=(
                        f"{routing_hint}: treat casual chat or unaccepted work as if "
                        "this workflow already produced verified results."
                    ),
                    expected=f"Ask a clarification question or route to a narrower workflow instead of forcing `{self.name}`.",
                    why="The request lacks the required inputs or would overclaim work that Hermes did not observe.",
                ),
            )
        if not self.final_checklist:
            object.__setattr__(
                self,
                "final_checklist",
                _default_final_checklist(self.name, self.category, self.hermes_role, self.quality_tier),
            )
        if not self.recovery_notes:
            object.__setattr__(
                self,
                "recovery_notes",
                _default_recovery_notes(self.name, self.category, self.hermes_role, self.quality_tier),
            )


_DEFAULT_GOOD_EXAMPLES = {
    "ralph": SkillExample(
        prompt="ralph: finish the invoice export recovery until the smoke test passes or a blocker is recorded.",
        expected="Keep one completion owner, track evidence after every recovery step, and stop only on pass, block, or explicit cancel.",
        why="The request needs persistent completion pressure with an observable stop condition.",
    ),
    "team": SkillExample(
        prompt="team: coordinate parallel agents for frontend polish, copy polish, and QA with worker ACKs.",
        expected="Assign lanes, require worker ACK/result evidence, and keep integration verification separate.",
        why="The work benefits from multiple coordinated workers with disjoint ownership.",
    ),
    "research-brief": SkillExample(
        prompt="research-brief: compare three onboarding analytics vendors using customer notes and confidence gaps.",
        expected="Prepare a source-backed brief with evidence, inference, confidence, and retrieval gaps separated.",
        why="The user needs business research synthesis, not recurring operations or coding.",
    ),
    "strategy-brief": SkillExample(
        prompt="strategy-brief: decide whether our onboarding should prioritize solo founders or enterprise buyers.",
        expected="Frame options, tradeoffs, assumptions, rejected paths, and the decision evidence needed.",
        why="The request is strategy-shaped and should not jump directly into implementation.",
    ),
    "ops-review": SkillExample(
        prompt="ops-review: summarize this week’s support queue, release blockers, owner status, and next operating risks.",
        expected="Create an operations status review with owners, blockers, evidence gaps, and next actions.",
        why="The request is an operating review rather than a one-off plan or coding handoff.",
    ),
    "idea-to-deploy": SkillExample(
        prompt="idea-to-deploy: turn this onboarding idea into a scoped plan, implementation handoff, QA gate, and release path.",
        expected="Prepare the idea-to-release lane while keeping implementation, QA, and deploy evidence observed-only.",
        why="The request spans product shaping through deploy readiness instead of a single task.",
    ),
    "cto-loop": SkillExample(
        prompt="cto-loop: run the PM, dev, QA, security, and ops loop for this risky billing launch.",
        expected="Prepare the CTO operating model with role responsibilities, gates, blockers, and status boundaries.",
        why="The request needs a leadership operating loop, not just a generic plan.",
    ),
    "deploy-and-monitor": SkillExample(
        prompt="deploy-and-monitor: prepare the release monitor, rollback signals, health checks, and post-deploy status card.",
        expected="Create release monitoring guidance with deployment, metric, rollback, and observation boundaries.",
        why="The request is about deploy readiness and monitoring rather than code review alone.",
    ),
    "ultraqa": SkillExample(
        prompt="$ultraqa test the setup wizard with hostile install paths, stale config, and missing PATH cases.",
        expected="Generate adversarial QA scenarios, expected signals, observed results, and fix-or-retry routing.",
        why="The request asks for verification pressure and hostile scenarios.",
    ),
    "ai-slop-cleaner": SkillExample(
        prompt="$ai-slop-cleaner remove duplicated router branches and lock behavior with regression tests before refactoring.",
        expected="Plan cleanup, preserve behavior, delete or simplify code, and prove it with targeted tests.",
        why="The request is maintenance cleanup with regression risk.",
    ),
    "best-practice-research": SkillExample(
        prompt="best-practice-research: check official docs and upstream examples before we choose the plugin packaging pattern.",
        expected="Gather primary-source guidance, compare options, and separate evidence from recommendation.",
        why="The request needs citation-backed best-practice research before implementation.",
    ),
    "autoresearch-goal": SkillExample(
        prompt="autoresearch-goal: keep researching AI agent memory practices until the evidence gaps are closed or logged.",
        expected="Run a durable research loop with critic checks, source gaps, and a stop or checkpoint condition.",
        why="The request is research that needs persistence and review, not a one-shot brief.",
    ),
    "performance-goal": SkillExample(
        prompt="performance-goal: benchmark recommendation latency, optimize hot paths safely, and prove no regressions.",
        expected="Create a measurement-led optimization loop with baseline, change, verification, and regression evidence.",
        why="The request is performance optimization and needs measured before/after proof.",
    ),
    "wiki": SkillExample(
        prompt="wiki: six of us keep re-answering the same questions in chat; help me stand up a wiki in Notion.",
        expected=(
            "Ask who reads and maintains it and what knowledge repeats, then propose one model with its breaking "
            "conditions, a skeleton, and seed pages, without claiming the store was created."
        ),
        why="The request is wiki construction for a shared audience, not a single note capture or connector execution.",
    ),
    "ask": SkillExample(
        prompt="ask: ask Claude as an external advisor to critique this plugin bridge plan before implementation.",
        expected="Prepare an advisor prompt, capture the response boundary, and summarize reusable critique.",
        why="The user wants outside review before committing to a direction.",
    ),
    "skill": SkillExample(
        prompt="$skill list installed OMH skills and show the catalog metadata for each workflow.",
        expected="Manage or inspect the skill catalog without claiming runtime execution or external evidence.",
        why="The request is operator skill management, not a user workflow run.",
    ),
}


# The per-engine lifecycle ladder for the ULW consolidation (#954). The stage
# is an independent field, not a derivation of `compatibility_alias`: a retired
# engine keeps `compatibility_alias=True` so a stale workflow hint still
# resolves as a compatibility concern rather than a generic non-routable name.
SURFACE_LIFECYCLE_STAGES = ("canonical", "alias", "warning", "retired")


@dataclass(frozen=True)
class SurfaceExposure:
    name: str
    exposure: str
    projections: tuple[str, ...]
    install_visibility: bool
    docs_visibility: str
    preferred_usage: str
    compatibility_alias: bool = False
    lifecycle_stage: str = "canonical"
    target_home: str | None = None
    migration_release: str | None = None


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
    quality_tier: str = "evidence-gated"
    quality_bar: tuple[str, ...] = (
        "State the lane objective, required inputs, expected outputs, and stop condition before claiming completion.",
        "Record only metadata-safe evidence and leave unavailable delegation explicit.",
    )
    evidence_ladder: tuple[str, ...] = (
        "request_received",
        "lane_started",
        "evidence_recorded",
        "result_reported",
    )
    wrapper_actions: tuple[str, ...] = ("show_status",)
    overclaim_guards: tuple[str, ...] = (
        "Do not upgrade requested or prepared work into observed completion without runtime or wrapper evidence.",
    )


CODING_INTENTS = ("coding", "cleanup", "review", "planning", "diagnostics", "docs", "unknown")
CODING_INTENT_PRIORITY = ("cleanup", "review", "planning", "diagnostics", "docs", "coding")
CODING_INTENT_TERMS = {
    "cleanup": ("cleanup", "clean", "refactor", "deslop", "legacy", "리팩터링", "리팩토링", "레거시", "회귀 테스트"),
    "review": (
        "review",
        "audit",
        "critic",
        "critique",
        "release gate",
        "claim",
        "evidence boundary",
        "리뷰",
        "릴리즈 전",
        "릴리즈",
        "과장",
        "실제 코드",
        "실제로 뭐 했는지",
    ),
    "planning": (
        "plan",
        "planning",
        "strategy",
        "architecture",
        "design",
        "proposal",
        "triage",
        "issue to pr",
        "acceptance criteria",
        "verification command",
        "workflow",
        "pipeline",
        "handoff",
        "idea to deploy",
        "from idea to deploy",
        "plan to deploy",
        "cto loop",
        "roadmap",
        "launch",
        "deploy and monitor",
        "rollback",
        "계획",
        "기획",
        "조사",
        "재현 계획",
        "이슈",
        "pr로",
        "요구사항",
        "온보딩",
        "고객 피드백",
        "기능 요청",
        "고객사",
        "프로젝트별",
        "작업 허브",
        "상태와 다음 행동",
        "아이디어부터 배포",
        "기획부터 배포",
        "완제품 루프",
        "출시",
        "배포 모니터링",
        "롤백",
    ),
    "diagnostics": (
        "diagnose",
        "doctor",
        "debug",
        "health",
        "broken",
        "failing",
        "failure",
        "incident",
        "reproduce",
        "결제 실패",
        "실패",
        "버그",
        "장애",
        "진단",
        "재현",
    ),
    "docs": ("docs", "documentation", "readme", "guide", "wiki", "문서", "가이드", "운영자 가이드"),
    "coding": ("code", "implement", "build", "fix", "change", "modify", "add", "write", "구현", "수정", "추가", "변경", "고쳐", "만들"),
}
CODING_REVIEW_TERMS = (
    *CODING_INTENT_TERMS["review"],
    "risky",
    "risk",
    "migration",
    "security",
    "public api",
    "위험",
    "릴리즈",
)
_CODING_INTENT_BY_SKILL = {
    "ai-slop-cleaner": "cleanup",
    "code-review": "review",
    "context": "planning",
    "plan": "planning",
    "ralplan": "planning",
    "research-brief": "planning",
    "strategy-brief": "planning",
    "meeting-brief": "planning",
    "feedback-triage": "planning",
    "ops-review": "planning",
    "operating-rhythm": "planning",
    "report-package": "planning",
    "materials-package": "planning",
    "img-summary": "planning",
    "design-quality-gate": "planning",
    "frontend": "planning",
    "accessibility-audit": "planning",
    "visual-qa": "planning",
    "failure-signal-audit": "planning",
    "paper-learning": "planning",
    "source-finder": "planning",
    "workspace-audit": "planning",
    "production-audit": "planning",
    "verification-gate": "planning",
    "build-failure-triage": "planning",
    "agent-evaluation": "planning",
    "rules-distill": "planning",
    "codebase-onboarding": "planning",
    "codegraph-refresh": "planning",
    "context-budget-review": "planning",
    "security-safety-review": "planning",
    "automation-blueprint": "planning",
    "reliability-review": "planning",
    "idea-to-deploy": "planning",
    "cto-loop": "planning",
    "deploy-and-monitor": "planning",
    "loop": "planning",
    "ultraprocess": "planning",
    "best-practice-research": "planning",
    "research": "planning",
    "ultraqa": "diagnostics",
    "doctor": "diagnostics",
    "wiki": "docs",
}
_CODING_INTENT_BY_SKILL.update(
    {
        "github-event-ops": "planning",
        "agent-board": "planning",
        "memory-new": "planning",
        "memory-sync": "planning",
        "gateway-intent-card": "planning",
        "executor-runtime-readiness": "planning",
        "deliverable-package": "planning",
        "voice-operator": "planning",
        "browser-operator": "planning",
        "workspace-file-operator": "planning",
        "command-operator": "planning",
        "connector-operator": "planning",
        "live-info-operator": "planning",
        "external-connector-readiness": "planning",
        "prompt-import-readiness": "planning",
        "physical-device-readiness": "planning",
        "content-operator": "planning",
        "media-input-operator": "planning",
        "data-analysis": "planning",
        "toolbelt-readiness": "planning",
        "harness-session-inventory": "planning",
        "ops-observability-card": "planning",
        "achievements": "planning",
        "agent-ops-review": "planning",
        "agent-debug": "planning",
        "failure-signal-audit": "planning",
        "instinct-ledger": "planning",
        "skill-scout": "planning",
        "skill-health": "planning",
        "workflow-learning": "planning",
    }
)


def _feature_surface_skill(
    name: str,
    description: str,
    triggers: tuple[str, ...],
    use_when: str,
    *,
    category: str,
    phase: str,
    next_action: str,
    boundary: str,
    good_prompt: str,
    bad_prompt: str,
    expected_outputs: tuple[str, ...] | None = None,
    artifact_expectations: tuple[str, ...] | None = None,
    final_checklist: tuple[str, ...] | None = None,
    recovery_notes: tuple[str, ...] | None = None,
    extra_safety_rules: tuple[str, ...] = (),
    extra_quality_bar: tuple[str, ...] = (),
) -> SkillDefinition:
    return SkillDefinition(
        name,
        description,
        triggers,
        use_when,
        category=category,
        phase=phase,
        hermes_role="retained-operator",
        delegation_boundary="retained-catalog-intent",
        handoff_policy=(
            "Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, "
            "or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded."
        ),
        required_inputs=("user request", "target context", "delivery or status expectation", "known missing evidence"),
        expected_outputs=expected_outputs
        or (f"{name}/v1 card or guidance", "next action", "prepared-vs-observed boundary"),
        artifact_expectations=artifact_expectations
        or (f"{name}/v1 metadata-only runtime or wrapper card when recorded",),
        safety_rules=(
            boundary,
            "Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.",
            *extra_safety_rules,
        ),
        quality_tier="workflow-surface-gated",
        quality_bar=(
            "Name the user-facing workflow objective, required context, next action, and stop condition.",
            "Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.",
            "Expose missing tools, credentials, targets, or observations as user-visible gaps.",
            *extra_quality_bar,
        ),
        why_this_exists=(
            f"`{name}` exists so Hermes users can ask for this workflow in chat and receive a structured, "
            "evidence-bounded OMH operating surface instead of ad hoc narration."
        ),
        do_not_use_when=(
            "The request is already handled by a narrower explicit skill with stronger evidence.",
            "The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.",
            "The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.",
        ),
        good_example=SkillExample(
            prompt=good_prompt,
            expected=f"Produce `{next_action}` with required context, wrapper actions, and not-evidence boundaries.",
            why="The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.",
        ),
        bad_example=SkillExample(
            prompt=bad_prompt,
            expected="Report the missing observed evidence or authority instead of claiming the external step happened.",
            why="Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.",
        ),
        final_checklist=final_checklist or (),
        recovery_notes=recovery_notes or (),
    )
