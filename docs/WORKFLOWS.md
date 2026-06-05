# Workflow Reference

This file is generated from `src/skills/catalog.py`. Update the catalog first, then refresh this document.

The reference describes prompt-level Hermes workflow guidance and local evidence expectations. It does not claim hidden Hermes runtime behavior.

## Skills

### oh-my-hermes

Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.

- Category: `router`
- Phase: `routing`
- Use when: Use as the top-level router when a request references oh-my-hermes, installed workflows, or ambiguous workflow routing.
- Strong routing signals: `oh-my-hermes`, `omh`, `skill routing`, `workflow routing`
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
- Use when: Use after scope is concrete and the user wants one owner to continue through implementation and verification.
- Strong routing signals: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
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
- Use when: Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.
- Strong routing signals: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
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
- Use when: Use before planning or execution when requirements are materially ambiguous.
- Strong routing signals: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`
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
- Use when: Use when multiple independent lanes materially improve throughput or verification.
- Strong routing signals: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
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

### ultraqa

Hermes UltraQA workflow: adversarial QA and fix loops.

- Category: `verification`
- Phase: `qa`
- Use when: Use when the task needs adversarial test scenarios, verification, and fix loops.
- Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`
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
- Use when: Use for structured planning when implementation is not ready to start safely.
- Strong routing signals: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`
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
- Use when: Use when requirements are clear enough for planning but architecture, risks, or tests need review.
- Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`
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
- Use when: Use for review-shaped requests; findings come first and must cite concrete evidence.
- Strong routing signals: `code-review`, `$code-review`, `review`, `audit`, `find bugs`
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
- Use when: Use for behavior-preserving cleanup with tests before and after edits.
- Strong routing signals: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`
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
- Use when: Use when correctness depends on current official or upstream guidance.
- Strong routing signals: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
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
- Use when: Use for validator-gated research that needs durable artifacts.
- Strong routing signals: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
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
- Use when: Use when the goal is measurable performance improvement with evaluator evidence.
- Strong routing signals: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
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
- Use when: Use to capture durable project knowledge in markdown artifacts.
- Strong routing signals: `wiki`, `project wiki`, `memory`, `notes`
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
- Use when: Use only when an external advisor is configured and would materially improve the answer.
- Strong routing signals: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
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
- Use when: Use to cleanly end active adapted workflow state.
- Strong routing signals: `cancel`, `$cancel`, `stop`, `abort`
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
- Use when: Use for local skill listing, search, add, remove, or edit tasks.
- Strong routing signals: `skill`, `$skill`, `skills`, `manage skills`
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
- Use when: Use to diagnose OMH installation and Hermes config registration.
- Strong routing signals: `doctor`, `$doctor`, `diagnose omh`, `installation health`
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
- Artifact events:
  - `run_started`
  - `coding_delegation_recorded`
  - `verification_recorded`
- Delegation expectation: Record prepared coding delegation with omh coding delegate; record observed execution only when Hermes exposes a separate coding, review, or verification lane.
- Privacy default: `metadata_only`
- Fallback: If the request is underspecified, ask one concise clarification question before editing.

### goal-execution

Keep long-running work tied to explicit goals, checkpoints, and durable evidence.

- Use when: Use when the task has multiple milestones, durable state, or finish-until-done pressure.
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
- Artifact events:
  - `goal_started`
  - `checkpoint_recorded`
  - `goal_completed_or_blocked`
- Delegation expectation: Record goal/delegation participants only when the active Hermes runtime exposes them.
- Privacy default: `metadata_only`
- Fallback: If Hermes has no goal tool, use a local checklist or file-backed ledger.

### planning

Turn clarified requirements into an execution-ready plan with tradeoffs and tests.

- Use when: Use before implementation when architecture, sequencing, or validation shape matters.
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
- Artifact events:
  - `plan_started`
  - `options_reviewed`
  - `handoff_recorded`
- Delegation expectation: Record planner, architect, or reviewer delegation only when observed in Hermes metadata or wrapper logs.
- Privacy default: `metadata_only`
- Fallback: If consensus review is unavailable, do a sequential planner -> reviewer pass.

### deep-interview

Clarify intent and boundaries one question at a time before planning or execution.

- Use when: Use when intent, scope, non-goals, or decision authority are unclear.
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
- Artifact events:
  - `interview_started`
  - `question_asked`
  - `clarity_recorded`
- Delegation expectation: Record a delegated interviewer only when Hermes exposes that lane; otherwise record sequential clarification.
- Privacy default: `metadata_only`
- Fallback: If structured question UI is unavailable, ask one direct question in the current surface.

### architect

Evaluate system boundaries, integration choices, and long-term maintainability.

- Use when: Use when a plan touches architecture, runtime integration, extension boundaries, or shared contracts.
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
- Artifact events:
  - `architecture_review_started`
  - `tradeoff_recorded`
  - `verdict_recorded`
- Delegation expectation: Record architect delegation only when Hermes exposes an architect lane or wrapper-side role result.
- Privacy default: `metadata_only`
- Fallback: If delegation is unavailable, run a separate self-review pass before coding.

### critic

Challenge plan consistency, quality criteria, and missing verification.

- Use when: Use after planning or before release when a bad assumption would be costly.
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
- Artifact events:
  - `critic_review_started`
  - `finding_recorded`
  - `verdict_recorded`
- Delegation expectation: Record critic delegation only when Hermes exposes a critic lane or wrapper-side role result.
- Privacy default: `metadata_only`
- Fallback: If no critic role exists, do a bug-first checklist review and cite concrete evidence.

### qa-specialist

Design adversarial scenarios and verify user-visible behavior before completion.

- Use when: Use when changes affect workflows, installer behavior, docs examples, or routing claims.
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
- Artifact events:
  - `qa_started`
  - `scenario_recorded`
  - `pass_fail_recorded`
- Delegation expectation: Record QA delegation only when Hermes exposes a QA lane or wrapper-side QA result.
- Privacy default: `metadata_only`
- Fallback: If runtime automation is unavailable, use fixtures and document manual checks.

### docs-specialist

Keep public docs accurate, installable, and aligned with actual behavior.

- Use when: Use whenever user-facing commands, routing behavior, examples, or release posture change.
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
- Artifact events:
  - `docs_review_started`
  - `claim_checked`
  - `docs_updated`
- Delegation expectation: Record docs delegation only when Hermes exposes a docs lane or wrapper-side docs result.
- Privacy default: `metadata_only`
- Fallback: If behavior is not implemented yet, label it as roadmap instead of current capability.
