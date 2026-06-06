# Workflow Reference

This file is generated from `src/skills/catalog.py`. Update the catalog first, then refresh this document.

The reference describes prompt-level Hermes workflow guidance and local evidence expectations. It does not claim hidden Hermes runtime behavior.

Workflow names are kept for compatibility, but each skill declares advisory wrapper guidance for whether Hermes should retain the work directly or prepare a Codex handoff for coding-heavy execution.

## Skills

### oh-my-hermes

Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.

- Category: `router`
- Phase: `routing`
- Hermes role: `retained-router`
- Quality tier: `routing-gated`
- Handoff policy: Classify requests into Hermes-retained planning/research/interview lanes or prepared Codex coding handoffs; do not execute code.
- Use when: Use as the top-level router when a request references oh-my-hermes, installed workflows, or ambiguous workflow routing.
- Strong routing signals: `oh-my-hermes`, `omh`, `skill routing`, `workflow routing`
- Quality bar:
  - Route only from explicit invocation, strong catalog evidence, or a clear workflow-shaped request.
  - Return a clarification or fallback path instead of forcing low-confidence messages into a workflow.
  - Keep users command-agnostic by naming the next UX step rather than shell commands.
- Required inputs:
  - user request
  - installed skill descriptions
  - Hermes skill discovery context
- Expected outputs:
  - selected workflow guidance
  - clarification question when routing is ambiguous
- Artifact expectations:
  - runtime run record when a wrapper can observe request handling
- Safety rules:
  - Prefer explicit skill invocation over weak keyword inference.
  - Ask one concise question when routing signals conflict.
  - Do not claim to override Hermes core routing.

### ralph

Hermes Ralph workflow: persistent execution with verification and review.

- Category: `execution`
- Phase: `completion`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `handoff-gated`
- Handoff policy: Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track a Codex lifecycle instead of making Hermes the coder.
- Use when: Use after scope is concrete and the user wants one owner to continue through implementation and verification.
- Strong routing signals: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- Quality bar:
  - Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
  - For coding edits, prepare and track Codex-like executor evidence instead of implying Hermes implemented the changes.
  - Report completion only from observed execution and verification evidence.
- Required inputs:
  - concrete scope
  - acceptance criteria
  - verification commands
- Expected outputs:
  - completed work summary
  - verification evidence
  - remaining risks
- Artifact expectations:
  - goal-execution run record
  - checkpoint or final evidence when available
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### ultragoal

Hermes Ultragoal workflow: file-backed durable goal ledgers.

- Category: `execution`
- Phase: `durable-goals`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `checkpoint-gated`
- Handoff policy: Use Hermes to maintain durable goal/checkpoint state; delegate coding milestones to Codex and report only observed runtime evidence.
- Use when: Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.
- Strong routing signals: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
- Quality bar:
  - Keep goal state durable, inspectable, and separate from chat narration.
  - Checkpoint every success, blocker, and final quality gate with fresh evidence.
  - For coding milestones, use prepared handoffs and observed executor evidence rather than hidden Hermes execution.
- Required inputs:
  - goal statement
  - acceptance criteria
  - current checkpoint
- Expected outputs:
  - goal ledger updates
  - checkpoint evidence
  - completion or blocker summary
- Artifact expectations:
  - goal ledger or checklist
  - runtime run record for each major checkpoint
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### deep-interview

Hermes Deep Interview workflow: one-question-at-a-time clarification.

- Category: `clarification`
- Phase: `discovery`
- Hermes role: `retained-cognition`
- Quality tier: `clarity-gated`
- Handoff policy: Run directly in Hermes or the chat wrapper; produce a clarified brief before any Codex handoff is prepared.
- Use when: Use before planning or execution when requirements are materially ambiguous.
- Strong routing signals: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`
- Quality bar:
  - Ask exactly one blocking question per turn unless the wrapper explicitly supports a structured batch.
  - Tie each question to a missing decision that changes the plan, handoff, or stop condition.
  - Emit a clarified brief with non-goals and acceptance criteria before planning or delegation.
- Required inputs:
  - initial request
  - known repo facts
  - current ambiguity
- Expected outputs:
  - clarified brief
  - non-goals
  - decision boundaries
- Artifact expectations:
  - clarity summary or transcript when the wrapper supports it
- Safety rules:
  - Ask one question at a time.
  - Gather discoverable repo facts before asking the user.
  - Stop interviewing once ambiguity is low enough to plan.

### team

Hermes Team workflow: coordinated parallel or sequential work lanes.

- Category: `execution`
- Phase: `coordination`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `coordination-gated`
- Handoff policy: Use Hermes for lane framing and status; implementation lanes should become Codex handoff tasks unless they are research, interview, planning, or status-only.
- Use when: Use when multiple independent lanes materially improve throughput or verification.
- Strong routing signals: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- Quality bar:
  - Split only independent lanes with explicit ownership and verification boundaries.
  - Keep Hermes as coordinator and status narrator while coding lanes become executor handoffs.
  - Integrate lane evidence before reporting combined progress.
- Required inputs:
  - bounded lane definitions
  - ownership boundaries
  - verification target
- Expected outputs:
  - lane results
  - integration summary
  - combined verification evidence
- Artifact expectations:
  - delegation record only when separate participants are observed
- Safety rules:
  - Use parallel lanes only when work is independent.
  - Keep shared-file edits under one owner.
  - Record unobserved delegation as not_observed.

### ultrawork

Hermes Ultrawork compatibility workflow: bounded parallel delivery guidance.

- Category: `execution`
- Phase: `parallel-delivery`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `handoff-gated`
- Handoff policy: Keep the workflow name for compatibility, but convert coding lanes into explicit Codex handoffs with disjoint scope, verification, and review evidence.
- Use when: Use when an accepted implementation plan can be split into independent, reviewable work lanes.
- Strong routing signals: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- Quality bar:
  - Require disjoint lane ownership before preparing multiple coding handoffs.
  - Attach acceptance criteria, verification commands, and review expectations to each lane.
  - Keep dispatch, execution, review, CI, and merge status evidence separate.
- Required inputs:
  - accepted plan
  - lane list
  - disjoint file or responsibility scopes
  - verification commands
- Expected outputs:
  - Codex handoff prompts or lane instructions
  - status summary
  - review/CI evidence requirements
- Artifact expectations:
  - prepared coding delegation record per implementation lane when wrappers can record them
- Safety rules:
  - Do not start parallel coding without disjoint ownership boundaries.
  - Keep Hermes responsible for orchestration/status, not hidden implementation.
  - Record unobserved Codex execution as prepared_not_observed or not_observed.

### web-research

Hermes Web Research workflow: source-backed current information gathering.

- Category: `research`
- Phase: `current-evidence`
- Hermes role: `retained-cognition`
- Quality tier: `source-gated`
- Handoff policy: Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.
- Use when: Use when the user needs current web evidence, links, citations, or source comparison before planning or handoff.
- Strong routing signals: `web-research`, `web research`, `latest`, `current sources`, `source-backed research`
- Quality bar:
  - Use official or primary sources first when current or external facts matter.
  - Separate direct evidence, inference, confidence, and residual uncertainty.
  - Summarize research before any coding handoff; research is not implementation evidence.
- Required inputs:
  - research question
  - source boundaries
  - recency or jurisdiction constraints
- Expected outputs:
  - source-backed synthesis
  - links or citations
  - confidence and residual uncertainty
- Artifact expectations:
  - research notes with source URLs when the wrapper captures them
- Safety rules:
  - Prefer official or primary sources when they can answer the question.
  - Separate quoted evidence from inference.
  - State retrieval limits and dates for unstable facts.

### ultraqa

Hermes UltraQA workflow: adversarial QA and fix loops.

- Category: `verification`
- Phase: `qa`
- Hermes role: `hybrid-verification`
- Quality tier: `scenario-gated`
- Handoff policy: Hermes can design scenarios and report observed results; code fixes discovered by QA should become Codex handoffs.
- Use when: Use when the task needs adversarial test scenarios, verification, and fix loops.
- Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`
- Quality bar:
  - Generate hostile scenarios from changed behavior and known risk areas.
  - Report pass/fail evidence separately from proposed fixes.
  - Delegate code mutations discovered by QA to Codex-like executors.
- Required inputs:
  - changed behavior
  - acceptance criteria
  - known risk areas
- Expected outputs:
  - adversarial scenarios
  - pass/fail evidence
  - fix recommendations
- Artifact expectations:
  - QA scenario evidence
  - runtime verification summary
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### plan

Hermes Plan workflow: structured planning before execution.

- Category: `planning`
- Phase: `plan`
- Hermes role: `retained-cognition`
- Quality tier: `acceptance-gated`
- Handoff policy: Keep planning in Hermes; if the accepted plan requires code edits, prepare a Codex handoff after acceptance.
- Use when: Use for structured planning when implementation is not ready to start safely.
- Strong routing signals: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`
- Quality bar:
  - Make goals, non-goals, risks, acceptance criteria, and verification shape explicit.
  - Keep draft plans unapproved until a user or wrapper accepts them.
  - Only prepare coding handoff guidance after the plan is accepted.
- Required inputs:
  - requirements
  - constraints
  - known facts
  - non-goals
- Expected outputs:
  - plan
  - acceptance criteria
  - verification strategy
- Artifact expectations:
  - plan artifact when durable execution will follow
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### ralplan

Hermes Ralplan workflow: consensus planning with review gates.

- Category: `planning`
- Phase: `reviewed-plan`
- Hermes role: `retained-cognition`
- Quality tier: `reviewed-plan-gated`
- Handoff policy: Keep consensus planning and review in Hermes; produce explicit Codex handoff guidance only after the plan is accepted.
- Use when: Use when requirements are clear enough for planning but architecture, risks, or tests need review.
- Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`
- Quality bar:
  - Include a planner view, risk review, and testability check before handoff.
  - Record unresolved tradeoffs and rejected options instead of flattening uncertainty.
  - Do not implement directly from consensus planning.
- Required inputs:
  - requirements
  - options
  - tradeoffs
  - test shape
- Expected outputs:
  - approved plan
  - risk review
  - handoff guidance
- Artifact expectations:
  - plan and review artifacts when a wrapper supports file-backed planning
- Safety rules:
  - Do not implement directly from the planning lane.
  - Make acceptance criteria testable.
  - Record unresolved tradeoffs explicitly.

### code-review

Hermes Code Review workflow: bug-first review with evidence.

- Category: `review`
- Phase: `critique`
- Hermes role: `hybrid-review`
- Quality tier: `finding-evidence-gated`
- Handoff policy: Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to Codex.
- Use when: Use for review-shaped requests; findings come first and must cite concrete evidence.
- Strong routing signals: `code-review`, `$code-review`, `review`, `audit`, `find bugs`
- Quality bar:
  - Lead with ranked findings grounded in file, diff, command, or artifact evidence.
  - Separate review findings from fix implementation; fixes become executor work.
  - Say clearly when no actionable issue is found and name remaining test gaps.
- Required inputs:
  - diff or files
  - expected behavior
  - test evidence
- Expected outputs:
  - ranked findings
  - open questions
  - test gaps
- Artifact expectations:
  - critic run record when review evidence is captured
- Safety rules:
  - Findings come before summaries.
  - Cite concrete evidence for every finding.
  - Say clearly when no issue is found.

### ai-slop-cleaner

Hermes AI slop cleaner workflow: behavior-preserving cleanup.

- Category: `maintenance`
- Phase: `cleanup`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `regression-gated`
- Handoff policy: Use Hermes to define cleanup scope and regression checks; delegate behavior-preserving edits to Codex once tests are clear.
- Use when: Use for behavior-preserving cleanup with tests before and after edits.
- Strong routing signals: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`
- Quality bar:
  - Lock current behavior with regression checks before non-trivial cleanup.
  - Prefer deletion, reuse, and boundary repair over new abstractions.
  - Rerun verification after cleanup before claiming behavior is preserved.
- Required inputs:
  - target smell
  - current behavior
  - regression checks
- Expected outputs:
  - small cleanup diff
  - before/after verification
  - residual risk
- Artifact expectations:
  - cleanup plan and regression evidence for non-trivial work
- Safety rules:
  - Lock behavior with tests before risky cleanup.
  - Prefer deletion and existing utilities over new layers.
  - Do not add dependencies for cleanup unless explicitly requested.

### best-practice-research

Hermes adaptation for bounded official/upstream best-practice research.

- Category: `research`
- Phase: `evidence`
- Hermes role: `retained-cognition`
- Quality tier: `source-gated`
- Handoff policy: Run as Hermes-side evidence gathering; hand coding to Codex only after source-backed guidance is summarized.
- Use when: Use when correctness depends on current official or upstream guidance.
- Strong routing signals: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- Quality bar:
  - Use official or upstream sources first and name the version/environment assumptions.
  - Map applicability to the user's local context before recommending action.
  - Preserve residual uncertainty instead of overstating best practice.
- Required inputs:
  - chosen technology
  - question
  - version or environment constraints
- Expected outputs:
  - source-backed guidance
  - applicability notes
  - residual uncertainty
- Artifact expectations:
  - research notes or citations when the wrapper captures them
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### autoresearch-goal

Hermes adaptation for durable research-goal execution.

- Category: `research`
- Phase: `durable-research`
- Hermes role: `retained-cognition`
- Quality tier: `validator-gated`
- Handoff policy: Keep durable research in Hermes-managed artifacts; do not convert to Codex unless the research produces an accepted coding task.
- Use when: Use for validator-gated research that needs durable artifacts.
- Strong routing signals: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- Quality bar:
  - Define validator criteria before gathering evidence.
  - Keep durable research artifacts separate from coding execution evidence.
  - Stop with next questions or a source-backed synthesis when validation is incomplete.
- Required inputs:
  - research objective
  - validator criteria
  - source boundaries
- Expected outputs:
  - research artifact
  - validator result
  - next questions
- Artifact expectations:
  - durable research ledger or checklist
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### performance-goal

Hermes adaptation for measurable performance-goal execution.

- Category: `optimization`
- Phase: `measurement`
- Hermes role: `hybrid-measurement`
- Quality tier: `measurement-gated`
- Handoff policy: Hermes can own baselines, benchmark plans, and status; optimization code changes should be Codex handoffs.
- Use when: Use when the goal is measurable performance improvement with evaluator evidence.
- Strong routing signals: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- Quality bar:
  - Name the metric, baseline, budget, and benchmark command before optimizing.
  - Treat code-level optimization as executor work when edits are required.
  - Report deltas only from observed benchmark evidence.
- Required inputs:
  - metric
  - baseline
  - budget
  - benchmark command
- Expected outputs:
  - measurement delta
  - implementation summary
  - benchmark evidence
- Artifact expectations:
  - baseline and final benchmark evidence
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### wiki

Hermes adaptation for maintaining a project-local markdown wiki.

- Category: `knowledge`
- Phase: `capture`
- Hermes role: `retained-knowledge`
- Quality tier: `knowledge-gated`
- Handoff policy: Run directly in Hermes as knowledge capture unless the note reveals a separate coding task.
- Use when: Use to capture durable project knowledge in markdown artifacts.
- Strong routing signals: `wiki`, `project wiki`, `memory`, `notes`
- Quality bar:
  - Capture durable facts with source evidence and retrieval hints.
  - Mark stale or uncertain knowledge instead of presenting it as permanent truth.
  - Extract separate coding tasks instead of burying them in notes.
- Required inputs:
  - project fact
  - source evidence
  - target topic
- Expected outputs:
  - markdown note
  - retrieval hint
  - staleness warning when needed
- Artifact expectations:
  - repo-local markdown knowledge artifact
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### ask

Hermes adaptation for consulting an external advisor when configured.

- Category: `review`
- Phase: `external-advice`
- Hermes role: `hybrid-review`
- Quality tier: `evidence-gated`
- Handoff policy: Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.
- Use when: Use only when an external advisor is configured and would materially improve the answer.
- Strong routing signals: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - question
  - context summary
  - why external advice helps
- Expected outputs:
  - advisor summary
  - accepted/rejected advice
  - decision note
- Artifact expectations:
  - advisor transcript reference only when explicitly captured
- Safety rules:
  - Use only when configured and materially useful.
  - Treat advisor output as evidence to evaluate, not authority.
  - Do not send secrets or private prompts without explicit opt-in.

### cancel

Hermes adaptation for ending active workflow state cleanly.

- Category: `operator`
- Phase: `state-cleanup`
- Hermes role: `retained-operator`
- Quality tier: `evidence-gated`
- Handoff policy: Run directly in Hermes/runtime state; never delegate cancellation to Codex.
- Use when: Use to cleanly end active adapted workflow state.
- Strong routing signals: `cancel`, `$cancel`, `stop`, `abort`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - active workflow state
  - cancellation intent
- Expected outputs:
  - cleared state
  - safe stop summary
- Artifact expectations:
  - state clear record when state exists
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### skill

Hermes adaptation for managing local skills.

- Category: `operator`
- Phase: `skill-management`
- Hermes role: `retained-operator`
- Quality tier: `evidence-gated`
- Handoff policy: Use Hermes for inventory and guidance; delegate only repository code changes to Codex.
- Use when: Use for local skill listing, search, add, remove, or edit tasks.
- Strong routing signals: `skill`, `$skill`, `skills`, `manage skills`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - skill action
  - target skill name or directory
- Expected outputs:
  - skill inventory or mutation result
  - verification note
- Artifact expectations:
  - manifest update when managed skills change
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### doctor

Hermes adaptation for diagnosing oh-my-hermes installation health.

- Category: `operator`
- Phase: `diagnostics`
- Hermes role: `retained-operator`
- Quality tier: `evidence-gated`
- Handoff policy: Run directly as local health inspection; propose Codex work only when a repo fix is required.
- Use when: Use to diagnose OMH installation and Hermes config registration.
- Strong routing signals: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - omh home
  - Hermes home
  - observed issue
- Expected outputs:
  - health checks
  - fix guidance
  - known proof boundary
- Artifact expectations:
  - doctor state summary when runtime artifacts are writable
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

## Representative Harnesses

### coding-handling

Route implementation requests through scoped context, edit discipline, tests, review, and evidence.

- Use when: Use when the user asks Hermes to write, modify, debug, refactor, or review code.
- Quality tier: `handoff-gated`
- Quality bar:
  - Clarify scope before edits when target behavior, files, or verification are missing.
  - Attach acceptance criteria, verification expectations, and review expectations to the prepared handoff.
  - Report coding progress from lifecycle evidence, not from the existence of a prepared prompt.
- Inputs:
  - task statement
  - repo context
  - constraints
  - target files or discovered touchpoints
- Outputs:
  - changed files
  - verification evidence
  - remaining risks
- Stop conditions:
  - requested behavior is implemented
  - tests or checks pass
  - known gaps are reported
- Verification:
  - run the smallest relevant tests
  - inspect generated skill output when routing changed
- Evidence ladder:
  - `coding_delegation_prepared`
  - `executor_dispatch_observed`
  - `executor_result_observed`
  - `verification_recorded`
  - `review_ci_merge_recorded_when_required`
- Wrapper actions:
  - `accept_plan`
  - `send_to_codex`
  - `show_status`
  - `record_result`
- Artifact events:
  - `run_started`
  - `coding_delegation_recorded`
  - `verification_recorded`
- Delegation expectation: Record prepared coding delegation with omh coding delegate; record observed execution only when Hermes exposes a separate coding, review, or verification lane.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared coding_delegation.json is not implementation evidence.
  - Executor completion is not review, CI, merge-readiness, or merge evidence.
- Fallback: If the request is underspecified, ask one concise clarification question before editing.

### goal-execution

Keep long-running work tied to explicit goals, checkpoints, and durable evidence.

- Use when: Use when the task has multiple milestones, durable state, or finish-until-done pressure.
- Quality tier: `checkpoint-gated`
- Quality bar:
  - Create or reference a durable goal artifact before long-running progress claims.
  - Checkpoint complete, blocked, and failed states with evidence.
  - Run final verification and review gates before reporting a goal complete.
- Inputs:
  - goal statement
  - acceptance criteria
  - current checkpoint
  - blocked or pending stories
- Outputs:
  - goal ledger updates
  - checkpoint evidence
  - completion or blocker summary
- Stop conditions:
  - current goal is complete or explicitly blocked
  - checkpoint evidence is recorded
- Verification:
  - compare artifacts against acceptance criteria
  - record fresh evidence before completion
- Evidence ladder:
  - `goal_created`
  - `story_started`
  - `checkpoint_recorded`
  - `quality_gate_recorded`
  - `goal_closed`
- Wrapper actions:
  - `show_status`
  - `record_checkpoint`
  - `record_blocker`
  - `record_completion`
- Artifact events:
  - `goal_started`
  - `checkpoint_recorded`
  - `goal_completed_or_blocked`
- Delegation expectation: Record goal/delegation participants only when the active Hermes runtime exposes them.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A goal ledger entry is not proof that executor work ran.
  - Intermediate checkpoints cannot replace final verification and review evidence.
- Fallback: If Hermes has no goal tool, use a local checklist or file-backed ledger.

### planning

Turn clarified requirements into an execution-ready plan with tradeoffs and tests.

- Use when: Use before implementation when architecture, sequencing, or validation shape matters.
- Quality tier: `acceptance-gated`
- Quality bar:
  - Make goals, non-goals, decision drivers, options, risks, and test strategy explicit.
  - Keep draft plans unapproved until a user or wrapper accepts them.
  - Prepare coding handoff guidance only after acceptance.
- Inputs:
  - requirements
  - constraints
  - known facts
  - non-goals
- Outputs:
  - PRD or plan
  - test strategy
  - handoff guidance
- Stop conditions:
  - plan has acceptance criteria
  - risks and alternatives are explicit
- Verification:
  - review option consistency
  - verify testability before execution
- Evidence ladder:
  - `request_clarified`
  - `plan_drafted`
  - `options_reviewed`
  - `acceptance_recorded`
  - `handoff_ready`
- Wrapper actions:
  - `accept_plan`
  - `revise_plan`
  - `cancel`
  - `prepare_handoff`
- Artifact events:
  - `plan_started`
  - `options_reviewed`
  - `handoff_recorded`
- Delegation expectation: Record planner, architect, or reviewer delegation only when observed in Hermes metadata or wrapper logs.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A draft plan is not execution or review evidence.
  - Unobserved architect or critic review stays not_observed.
- Fallback: If consensus review is unavailable, do a sequential planner -> reviewer pass.

### research

Gather current or source-backed evidence before planning or coding handoff.

- Use when: Use when the request needs web/current/official source evidence or source comparison.
- Quality tier: `source-gated`
- Quality bar:
  - Use official or primary sources first when they can answer the question.
  - Separate source evidence, inference, confidence, and retrieval limits.
  - Record dates or version boundaries for unstable facts.
- Inputs:
  - research question
  - source boundaries
  - recency or environment constraints
- Outputs:
  - source-backed synthesis
  - links or citations
  - confidence and residual uncertainty
- Stop conditions:
  - claims are source-backed
  - retrieval limits and dates are explicit
- Verification:
  - prefer official or primary sources
  - separate evidence from inference
- Evidence ladder:
  - `research_question_scoped`
  - `sources_checked`
  - `evidence_synthesized`
  - `uncertainty_recorded`
- Wrapper actions:
  - `show_sources`
  - `ask_followup`
  - `prepare_plan`
- Artifact events:
  - `research_started`
  - `source_checked`
  - `synthesis_recorded`
- Delegation expectation: Record a research lane only when Hermes or the wrapper exposes source/research evidence; otherwise summarize retrieval limits explicitly.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Research synthesis is not implementation evidence.
  - Unavailable web access must be reported as a retrieval gap.
- Fallback: If web access is unavailable, state the retrieval gap and fall back to best available local evidence.

### deep-interview

Clarify intent and boundaries one question at a time before planning or execution.

- Use when: Use when intent, scope, non-goals, or decision authority are unclear.
- Quality tier: `clarity-gated`
- Quality bar:
  - Ask one blocking question tied to a missing decision.
  - Use discovered facts before asking the user for information already available locally.
  - Produce a clarified brief before planning or handoff.
- Inputs:
  - initial idea
  - current ambiguity
  - known repo facts
- Outputs:
  - clarified spec
  - non-goals
  - decision boundaries
  - acceptance criteria
- Stop conditions:
  - ambiguity is low enough
  - non-goals and decision boundaries are explicit
- Verification:
  - pressure-test assumptions
  - capture transcript or summary
- Evidence ladder:
  - `ambiguity_identified`
  - `question_asked`
  - `answer_recorded`
  - `clarified_brief_ready`
- Wrapper actions:
  - `answer:clarify`
  - `cancel`
  - `rerun_plan`
- Artifact events:
  - `interview_started`
  - `question_asked`
  - `clarity_recorded`
- Delegation expectation: Record a delegated interviewer only when Hermes exposes that lane; otherwise record sequential clarification.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A clarification question is not a plan approval.
  - Do not start a handoff while the blocking decision is unanswered.
- Fallback: If structured question UI is unavailable, ask one direct question in the current surface.

### architect

Evaluate system boundaries, integration choices, and long-term maintainability.

- Use when: Use when a plan touches architecture, runtime integration, extension boundaries, or shared contracts.
- Quality tier: `boundary-gated`
- Quality bar:
  - Check the proposed change against documented product and module boundaries.
  - Name rejected alternatives and long-term maintenance tradeoffs.
  - Require clear approval or concrete requested changes before implementation.
- Inputs:
  - plan
  - context
  - constraints
  - existing architecture evidence
- Outputs:
  - architecture verdict
  - tradeoff tension
  - required changes or clear approval
- Stop conditions:
  - boundary risks are addressed
  - chosen approach fits current architecture
- Verification:
  - steelman the strongest antithesis
  - check integration claims against evidence
- Evidence ladder:
  - `architecture_context_loaded`
  - `tradeoffs_recorded`
  - `boundary_verdict_recorded`
- Wrapper actions:
  - `show_review`
  - `revise_plan`
  - `approve_plan`
- Artifact events:
  - `architecture_review_started`
  - `tradeoff_recorded`
  - `verdict_recorded`
- Delegation expectation: Record architect delegation only when Hermes exposes an architect lane or wrapper-side role result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Sequential self-review is not observed architect delegation.
  - Architecture approval does not imply implementation or test success.
- Fallback: If delegation is unavailable, run a separate self-review pass before coding.

### critic

Challenge plan consistency, quality criteria, and missing verification.

- Use when: Use after planning or before release when a bad assumption would be costly.
- Quality tier: `finding-gated`
- Quality bar:
  - Challenge plan consistency, missing verification, and weak acceptance criteria.
  - Rank concrete findings before summaries.
  - Approve only when residual risks and test gaps are explicit.
- Inputs:
  - plan
  - test spec
  - architect review
  - user constraints
- Outputs:
  - approval or requested changes
  - critical findings
  - residual risks
- Stop conditions:
  - quality criteria are testable
  - risks have mitigations
  - alternatives are fair
- Verification:
  - check principle-option consistency
  - reject vague acceptance criteria
- Evidence ladder:
  - `review_scope_loaded`
  - `findings_recorded`
  - `verdict_recorded`
  - `residual_risk_recorded`
- Wrapper actions:
  - `show_findings`
  - `request_changes`
  - `approve_plan`
- Artifact events:
  - `critic_review_started`
  - `finding_recorded`
  - `verdict_recorded`
- Delegation expectation: Record critic delegation only when Hermes exposes a critic lane or wrapper-side role result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A critic verdict is not code-review evidence unless tied to actual diff/files.
  - Approval cannot erase missing downstream verification.
- Fallback: If no critic role exists, do a bug-first checklist review and cite concrete evidence.

### qa-specialist

Design adversarial scenarios and verify user-visible behavior before completion.

- Use when: Use when changes affect workflows, installer behavior, docs examples, or routing claims.
- Quality tier: `scenario-gated`
- Quality bar:
  - Derive adversarial scenarios from user-visible behavior and changed surfaces.
  - Record pass/fail evidence for critical scenarios.
  - Turn discovered code fixes into executor handoffs.
- Inputs:
  - acceptance criteria
  - changed behavior
  - fixtures or runnable commands
- Outputs:
  - test matrix
  - hostile scenarios
  - pass/fail evidence
- Stop conditions:
  - critical scenarios pass
  - known manual gaps are listed
- Verification:
  - run targeted tests
  - cover failure modes and recovery paths
- Evidence ladder:
  - `scenario_matrix_defined`
  - `checks_run`
  - `pass_fail_recorded`
  - `fix_followup_recorded_if_needed`
- Wrapper actions:
  - `show_status`
  - `record_check`
  - `record_blocker`
- Artifact events:
  - `qa_started`
  - `scenario_recorded`
  - `pass_fail_recorded`
- Delegation expectation: Record QA delegation only when Hermes exposes a QA lane or wrapper-side QA result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A scenario list is not pass evidence.
  - Failed QA cannot be summarized as complete without a blocker or fix record.
- Fallback: If runtime automation is unavailable, use fixtures and document manual checks.

### docs-specialist

Keep public docs accurate, installable, and aligned with actual behavior.

- Use when: Use whenever user-facing commands, routing behavior, examples, or release posture change.
- Quality tier: `claim-gated`
- Quality bar:
  - Check public claims against implemented behavior and known limitations.
  - Keep examples reproducible and avoid presenting roadmap as current capability.
  - Regenerate generated references from catalog data instead of hand-editing them.
- Inputs:
  - changed behavior
  - commands
  - limitations
  - audience
- Outputs:
  - README/docs updates
  - examples
  - troubleshooting notes
- Stop conditions:
  - docs match behavior
  - claims are conservative
  - examples are reproducible
- Verification:
  - run public-content scans
  - verify commands and file references
- Evidence ladder:
  - `claims_scoped`
  - `docs_updated`
  - `generated_docs_checked`
  - `public_claims_verified`
- Wrapper actions:
  - `show_docs`
  - `record_claim_check`
  - `show_status`
- Artifact events:
  - `docs_review_started`
  - `claim_checked`
  - `docs_updated`
- Delegation expectation: Record docs delegation only when Hermes exposes a docs lane or wrapper-side docs result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Documentation of a future adapter is not proof that a transport exists.
  - Generated docs must match catalog data before release claims are made.
- Fallback: If behavior is not implemented yet, label it as roadmap instead of current capability.
