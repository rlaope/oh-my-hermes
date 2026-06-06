---
name: oh-my-hermes
description: Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, router]
    category: router
    phase: routing
    role: retained-router
    quality_tier: routing-gated
---

# Oh My Hermes Router

Use this skill when the user mentions oh-my-hermes or a workflow keyword such as `ralph`, `ultragoal`, `ultrawork`, `deep-interview`, `web-research`, `team`, `ultraqa`, `ralplan`, or `code-review`.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact runtime parity with another agent framework.

Normal users should talk to Hermes Agent or invoke installed Hermes skills through Hermes' own skill surface. Do not ask chat users to run `omh` commands for ordinary workflow use. The `omh` command is bootstrap, maintenance, verification, and wrapper/backend infrastructure.

Hermes-native install paths should converge on the same skill-visible state:

- `hermes skills tap add rlaope/oh-my-hermes-agent`, then `hermes skills install oh-my-hermes` installs this tap-compatible skill pack directly when Hermes supports taps.
- `omh setup` installs generated managed skills and registers their directory through `skills.external_dirs` when a local bootstrap or repair path is preferred.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Skill Role Classification

Keep compatible workflow names installed, but use this advisory wrapper guidance to decide what Hermes should own:

- `oh-my-hermes`: role `retained-router`; handoff policy: Classify requests into Hermes-retained planning/research/interview lanes or prepared Codex coding handoffs; do not execute code.
- `ralph`: role `codex-handoff-guidance`; handoff policy: Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track a Codex lifecycle instead of making Hermes the coder.
- `ultragoal`: role `codex-handoff-guidance`; handoff policy: Use Hermes to maintain durable goal/checkpoint state; delegate coding milestones to Codex and report only observed runtime evidence.
- `deep-interview`: role `retained-cognition`; handoff policy: Run directly in Hermes or the chat wrapper; produce a clarified brief before any Codex handoff is prepared.
- `team`: role `codex-handoff-guidance`; handoff policy: Use Hermes for lane framing and status; implementation lanes should become Codex handoff tasks unless they are research, interview, planning, or status-only.
- `ultrawork`: role `codex-handoff-guidance`; handoff policy: Keep the workflow name for compatibility, but convert coding lanes into explicit Codex handoffs with disjoint scope, verification, and review evidence.
- `web-research`: role `retained-cognition`; handoff policy: Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.
- `ultraqa`: role `hybrid-verification`; handoff policy: Hermes can design scenarios and report observed results; code fixes discovered by QA should become Codex handoffs.
- `plan`: role `retained-cognition`; handoff policy: Keep planning in Hermes; if the accepted plan requires code edits, prepare a Codex handoff after acceptance.
- `ralplan`: role `retained-cognition`; handoff policy: Keep consensus planning and review in Hermes; produce explicit Codex handoff guidance only after the plan is accepted.
- `code-review`: role `hybrid-review`; handoff policy: Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to Codex.
- `ai-slop-cleaner`: role `codex-handoff-guidance`; handoff policy: Use Hermes to define cleanup scope and regression checks; delegate behavior-preserving edits to Codex once tests are clear.
- `best-practice-research`: role `retained-cognition`; handoff policy: Run as Hermes-side evidence gathering; hand coding to Codex only after source-backed guidance is summarized.
- `autoresearch-goal`: role `retained-cognition`; handoff policy: Keep durable research in Hermes-managed artifacts; do not convert to Codex unless the research produces an accepted coding task.
- `performance-goal`: role `hybrid-measurement`; handoff policy: Hermes can own baselines, benchmark plans, and status; optimization code changes should be Codex handoffs.
- `wiki`: role `retained-knowledge`; handoff policy: Run directly in Hermes as knowledge capture unless the note reveals a separate coding task.
- `ask`: role `hybrid-review`; handoff policy: Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.
- `cancel`: role `retained-operator`; handoff policy: Run directly in Hermes/runtime state; never delegate cancellation to Codex.
- `skill`: role `retained-operator`; handoff policy: Use Hermes for inventory and guidance; delegate only repository code changes to Codex.
- `doctor`: role `retained-operator`; handoff policy: Run directly as local health inspection; propose Codex work only when a repo fix is required.

General rule: Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. This role metadata is advisory unless a wrapper/runtime artifact records observed enforcement. When the accepted next action mutates code, the wrapper should prepare a Codex handoff and track the lifecycle instead of implying Hermes coded secretly.

## Wrapper Backend Chat Routing

Discord, Slack, or hosted Hermes wrappers can run `omh chat route` before dispatching a plain chat message to Hermes. This is an adapter/backend call, not end-user UX:

```sh
omh chat route --source discord --record "risky refactor"
```

Use `route.routing_prompt_template` with `{message}` replaced by the received chat message as the prompt forwarded to Hermes. If the wrapper does not log stdout and wants a pre-expanded prompt, pass `--include-message` and forward `route.routing_prompt`. A `dispatch` action targets the selected workflow skill; `clarify` and `fallback` target this router so Hermes can ask one concise follow-up instead of guessing.

This is a deterministic wrapper-side decision layer. By default, stdout and runtime artifacts avoid duplicating the raw prompt body. It does not patch Hermes core or require platform network access from `omh`.

## Wrapper Backend Coding Delegation

When a chat message is implementation-shaped and the wrapper wants a concrete executor handoff, run `omh coding delegate` after or instead of generic chat routing. This prepares adapter data; Hermes still narrates the user-facing state:

```sh
omh coding delegate --source discord --record "risky refactor"
```

The command returns a `coding_delegation/v1` payload with a recommended workflow, harness, executor profile, acceptance criteria, verification expectations, and a `delegation_prompt_template` that the wrapper can forward with the user message substituted. It is deterministic and uses only local catalog metadata.

With `--record`, `omh` writes `coding_delegation.json` under `.omh/runtime/runs/<run-id>/`. The companion `run.json` is marked with `status: prepared`, `artifact_kind: prepared_coding_delegation`, `phase: prepared`, and `observation_status: prepared_not_observed`. These artifacts store only allowlisted metadata, acceptance criteria, verification expectations, recommendation evidence, source references, `message_sha256`, and `message_length`. Validation treats the run envelope and `coding_delegation.json` as a required pair. They mean a coding handoff was prepared; they do not mean Hermes executed the work or that a specialist lane was observed.

## Hermes-Facing Planning

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to create a deterministic `hermes_plan/v1` planning scaffold. In normal chat, Hermes can express this plan directly through the installed skill guidance:

```sh
omh hermes plan --source discord --record "risky refactor with review"
```

With `--record`, `omh` writes a Markdown draft under `.hermes/plans/`. Weak requests also write `.hermes/context/` so Hermes can ask one blocking clarification before a final plan. The plan includes goals, non-goals, options, risks, acceptance criteria, verification, execution handoff guidance, and a review gate. Review gate entries default to `not_observed`; do not call the plan approved unless wrapper or human evidence proves the review happened.

The stdout `wrapper_contract` is the adapter contract for follow-on wrapper work. Use it instead of parsing the Markdown file. For implementation-shaped draft plans, `wrapper_contract.coding_delegate.argv_template` gives the exact `omh coding delegate --record` argv shape to run with the original message after plan acceptance. For blocked or non-coding plans, `coding_delegate.available` is `false`; follow `wrapper_contract.next_action` and do not dispatch a coding handoff.

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

- `ralph`: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- `ultragoal`: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
- `deep-interview`: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`
- `team`: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- `ultrawork`: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- `web-research`: `web-research`, `web research`, `latest`, `current sources`, `source-backed research`
- `ultraqa`: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`
- `plan`: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`
- `ralplan`: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`
- `code-review`: `code-review`, `$code-review`, `review`, `audit`, `find bugs`
- `ai-slop-cleaner`: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`
- `best-practice-research`: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- `autoresearch-goal`: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- `performance-goal`: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- `wiki`: `wiki`, `project wiki`, `memory`, `notes`
- `ask`: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- `cancel`: `cancel`, `$cancel`, `stop`, `abort`
- `skill`: `skill`, `$skill`, `skills`, `manage skills`
- `doctor`: `doctor`, `$doctor`, `diagnose omh`, `installation health`

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.

## Representative Harness Registry

Use these harnesses to shape the response before adding new skills. They are quality lanes, not proof that a separate runtime role exists.

- `coding-handling`: Route implementation requests through scoped context, edit discipline, tests, review, and evidence.
  - Use when: Use when the user asks Hermes to write, modify, debug, refactor, or review code.
  - Quality tier: `handoff-gated`
  - Inputs: task statement, repo context, constraints
  - Outputs: changed files, verification evidence, remaining risks
  - Quality Bar: Clarify scope before edits when target behavior, files, or verification are missing. Attach acceptance criteria, verification expectations, and review expectations to the prepared handoff. Report coding progress from lifecycle evidence, not from the existence of a prepared prompt.
  - Evidence Ladder: `coding_delegation_prepared` -> `executor_dispatch_observed` -> `executor_result_observed` -> `verification_recorded` -> `review_ci_merge_recorded_when_required`
  - Wrapper Actions: `accept_plan`, `send_to_codex`, `show_status`, `record_result`
  - Verification: run the smallest relevant tests, inspect generated skill output when routing changed
  - Runtime Evidence: events `run_started`, `coding_delegation_recorded`, `verification_recorded`; privacy `metadata_only`
  - Delegation: Record prepared coding delegation with omh coding delegate; record observed execution only when Hermes exposes a separate coding, review, or verification lane.
  - Overclaim Guards: A prepared coding_delegation.json is not implementation evidence. Executor completion is not review, CI, merge-readiness, or merge evidence.
  - Fallback: If the request is underspecified, ask one concise clarification question before editing.
- `goal-execution`: Keep long-running work tied to explicit goals, checkpoints, and durable evidence.
  - Use when: Use when the task has multiple milestones, durable state, or finish-until-done pressure.
  - Quality tier: `checkpoint-gated`
  - Inputs: goal statement, acceptance criteria, current checkpoint
  - Outputs: goal ledger updates, checkpoint evidence, completion or blocker summary
  - Quality Bar: Create or reference a durable goal artifact before long-running progress claims. Checkpoint complete, blocked, and failed states with evidence. Run final verification and review gates before reporting a goal complete.
  - Evidence Ladder: `goal_created` -> `story_started` -> `checkpoint_recorded` -> `quality_gate_recorded` -> `goal_closed`
  - Wrapper Actions: `show_status`, `record_checkpoint`, `record_blocker`, `record_completion`
  - Verification: compare artifacts against acceptance criteria, record fresh evidence before completion
  - Runtime Evidence: events `goal_started`, `checkpoint_recorded`, `goal_completed_or_blocked`; privacy `metadata_only`
  - Delegation: Record goal/delegation participants only when the active Hermes runtime exposes them.
  - Overclaim Guards: A goal ledger entry is not proof that executor work ran. Intermediate checkpoints cannot replace final verification and review evidence.
  - Fallback: If Hermes has no goal tool, use a local checklist or file-backed ledger.
- `planning`: Turn clarified requirements into an execution-ready plan with tradeoffs and tests.
  - Use when: Use before implementation when architecture, sequencing, or validation shape matters.
  - Quality tier: `acceptance-gated`
  - Inputs: requirements, constraints, known facts
  - Outputs: PRD or plan, test strategy, handoff guidance
  - Quality Bar: Make goals, non-goals, decision drivers, options, risks, and test strategy explicit. Record at least one rejected option and why it lost before presenting the preferred path. Tie every acceptance criterion to a validation command, artifact, or explicit manual evidence gap. Keep draft plans unapproved until a user or wrapper accepts them. Prepare coding handoff guidance only after acceptance.
  - Evidence Ladder: `request_clarified` -> `plan_drafted` -> `option_tradeoffs_recorded` -> `test_strategy_recorded` -> `acceptance_recorded` -> `handoff_ready`
  - Wrapper Actions: `accept_plan`, `revise_plan`, `cancel`, `prepare_handoff`
  - Verification: review option consistency, verify testability before execution
  - Runtime Evidence: events `plan_started`, `options_reviewed`, `handoff_recorded`; privacy `metadata_only`
  - Delegation: Record planner, architect, or reviewer delegation only when observed in Hermes metadata or wrapper logs.
  - Overclaim Guards: A draft plan is not execution or review evidence. Unobserved architect or critic review stays not_observed.
  - Fallback: If consensus review is unavailable, do a sequential planner -> reviewer pass.
- `research`: Gather current or source-backed evidence before planning or coding handoff.
  - Use when: Use when the request needs web/current/official source evidence or source comparison.
  - Quality tier: `source-gated`
  - Inputs: research question, source boundaries, recency or environment constraints
  - Outputs: source-backed synthesis, links or citations, confidence and residual uncertainty
  - Quality Bar: Scope the research question, source boundaries, recency, and jurisdiction or version assumptions before retrieval. Use official or primary sources first when they can answer the question. Record source quality, conflicting evidence, and retrieval gaps before synthesis. Separate source evidence, inference, confidence, and retrieval limits. Record dates or version boundaries for unstable facts.
  - Evidence Ladder: `research_question_scoped` -> `primary_sources_checked` -> `conflicts_checked` -> `evidence_synthesized` -> `uncertainty_recorded`
  - Wrapper Actions: `show_sources`, `ask_followup`, `prepare_plan`
  - Verification: prefer official or primary sources, separate evidence from inference
  - Runtime Evidence: events `research_started`, `source_checked`, `synthesis_recorded`; privacy `metadata_only`
  - Delegation: Record a research lane only when Hermes or the wrapper exposes source/research evidence; otherwise summarize retrieval limits explicitly.
  - Overclaim Guards: Research synthesis is not implementation evidence. Unavailable web access must be reported as a retrieval gap.
  - Fallback: If web access is unavailable, state the retrieval gap and fall back to best available local evidence.
- `deep-interview`: Clarify intent and boundaries one question at a time before planning or execution.
  - Use when: Use when intent, scope, non-goals, or decision authority are unclear.
  - Quality tier: `clarity-gated`
  - Inputs: initial idea, current ambiguity, known repo facts
  - Outputs: clarified spec, non-goals, decision boundaries
  - Quality Bar: Name the missing decision, why it matters, and the smallest answer that would unblock the next step. Ask one blocking question tied to a missing decision. Use discovered facts before asking the user for information already available locally. Produce a clarified brief with non-goals, acceptance criteria, and remaining unknowns before planning or handoff.
  - Evidence Ladder: `ambiguity_identified` -> `blocking_question_asked` -> `answer_recorded` -> `clarified_brief_ready`
  - Wrapper Actions: `answer:clarify`, `cancel`, `rerun_plan`
  - Verification: pressure-test assumptions, capture transcript or summary
  - Runtime Evidence: events `interview_started`, `question_asked`, `clarity_recorded`; privacy `metadata_only`
  - Delegation: Record a delegated interviewer only when Hermes exposes that lane; otherwise record sequential clarification.
  - Overclaim Guards: A clarification question is not a plan approval. Do not start a handoff while the blocking decision is unanswered.
  - Fallback: If structured question UI is unavailable, ask one direct question in the current surface.
- `architect`: Evaluate system boundaries, integration choices, and long-term maintainability.
  - Use when: Use when a plan touches architecture, runtime integration, extension boundaries, or shared contracts.
  - Quality tier: `boundary-gated`
  - Inputs: plan, context, constraints
  - Outputs: architecture verdict, tradeoff tension, required changes or clear approval
  - Quality Bar: Check the proposed change against documented product and module boundaries. Name rejected alternatives and long-term maintenance tradeoffs. Require clear approval or concrete requested changes before implementation.
  - Evidence Ladder: `architecture_context_loaded` -> `tradeoffs_recorded` -> `boundary_verdict_recorded`
  - Wrapper Actions: `show_review`, `revise_plan`, `approve_plan`
  - Verification: steelman the strongest antithesis, check integration claims against evidence
  - Runtime Evidence: events `architecture_review_started`, `tradeoff_recorded`, `verdict_recorded`; privacy `metadata_only`
  - Delegation: Record architect delegation only when Hermes exposes an architect lane or wrapper-side role result.
  - Overclaim Guards: Sequential self-review is not observed architect delegation. Architecture approval does not imply implementation or test success.
  - Fallback: If delegation is unavailable, run a separate self-review pass before coding.
- `critic`: Challenge plan consistency, quality criteria, and missing verification.
  - Use when: Use after planning or before release when a bad assumption would be costly.
  - Quality tier: `finding-gated`
  - Inputs: plan, test spec, architect review
  - Outputs: approval or requested changes, critical findings, residual risks
  - Quality Bar: Challenge plan consistency, missing verification, and weak acceptance criteria. Rank concrete findings before summaries. Approve only when residual risks and test gaps are explicit.
  - Evidence Ladder: `review_scope_loaded` -> `findings_recorded` -> `verdict_recorded` -> `residual_risk_recorded`
  - Wrapper Actions: `show_findings`, `request_changes`, `approve_plan`
  - Verification: check principle-option consistency, reject vague acceptance criteria
  - Runtime Evidence: events `critic_review_started`, `finding_recorded`, `verdict_recorded`; privacy `metadata_only`
  - Delegation: Record critic delegation only when Hermes exposes a critic lane or wrapper-side role result.
  - Overclaim Guards: A critic verdict is not code-review evidence unless tied to actual diff/files. Approval cannot erase missing downstream verification.
  - Fallback: If no critic role exists, do a bug-first checklist review and cite concrete evidence.
- `qa-specialist`: Design adversarial scenarios and verify user-visible behavior before completion.
  - Use when: Use when changes affect workflows, installer behavior, docs examples, or routing claims.
  - Quality tier: `scenario-gated`
  - Inputs: acceptance criteria, changed behavior, fixtures or runnable commands
  - Outputs: test matrix, hostile scenarios, pass/fail evidence
  - Quality Bar: Derive adversarial scenarios from user-visible behavior and changed surfaces. Record pass/fail evidence for critical scenarios. Turn discovered code fixes into executor handoffs.
  - Evidence Ladder: `scenario_matrix_defined` -> `checks_run` -> `pass_fail_recorded` -> `fix_followup_recorded_if_needed`
  - Wrapper Actions: `show_status`, `record_check`, `record_blocker`
  - Verification: run targeted tests, cover failure modes and recovery paths
  - Runtime Evidence: events `qa_started`, `scenario_recorded`, `pass_fail_recorded`; privacy `metadata_only`
  - Delegation: Record QA delegation only when Hermes exposes a QA lane or wrapper-side QA result.
  - Overclaim Guards: A scenario list is not pass evidence. Failed QA cannot be summarized as complete without a blocker or fix record.
  - Fallback: If runtime automation is unavailable, use fixtures and document manual checks.
- `docs-specialist`: Keep public docs accurate, installable, and aligned with actual behavior.
  - Use when: Use whenever user-facing commands, routing behavior, examples, or release posture change.
  - Quality tier: `claim-gated`
  - Inputs: changed behavior, commands, limitations
  - Outputs: README/docs updates, examples, troubleshooting notes
  - Quality Bar: Check public claims against implemented behavior and known limitations. Keep examples reproducible and avoid presenting roadmap as current capability. Regenerate generated references from catalog data instead of hand-editing them.
  - Evidence Ladder: `claims_scoped` -> `docs_updated` -> `generated_docs_checked` -> `public_claims_verified`
  - Wrapper Actions: `show_docs`, `record_claim_check`, `show_status`
  - Verification: run public-content scans, verify commands and file references
  - Runtime Evidence: events `docs_review_started`, `claim_checked`, `docs_updated`; privacy `metadata_only`
  - Delegation: Record docs delegation only when Hermes exposes a docs lane or wrapper-side docs result.
  - Overclaim Guards: Documentation of a future adapter is not proof that a transport exists. Generated docs must match catalog data before release claims are made.
  - Fallback: If behavior is not implemented yet, label it as roadmap instead of current capability.

Harness priority:

1. Coding requests start with `coding-handling`.
2. Multi-step durable work adds `goal-execution`.
3. Current-source or best-practice questions use the `research` harness and stay in Hermes-side evidence gathering before any coding handoff.
4. Unclear work uses `deep-interview` before `planning`.
5. Risky architecture uses `architect`, then `critic`.
6. User-visible behavior changes add `qa-specialist`.
7. Public commands, examples, or limitations add `docs-specialist`.

Recovery:

- If the right skill was not loaded, call `skills_list` or `skill_view`.
- If a slash command exists, use the explicit slash skill such as `/ralph`.
- If a skill name collides, ask the user whether to use the Hermes-native skill or the oh-my-hermes adapted skill.

## Hermes Compatibility

- Use Hermes tools and subagents when available.
- Replace unavailable goal tools with file-backed checklists or ledgers.
- Replace unavailable question renderers with one direct question through the current Hermes surface.
- Keep shell bridge behavior explicit and opt-in.

## Runtime Evidence

When local shell access or a bot wrapper is available, record prepared handoffs and observed workflow evidence under `.omh/runtime/`.

Examples:

```sh
omh coding delegate --source discord --record "risky refactor"
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record only what is observed. A `coding_delegation.json` record and its `prepared_coding_delegation` run envelope prove a prepared handoff, not execution. If Hermes does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.
