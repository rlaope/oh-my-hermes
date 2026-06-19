# Workflow Reference

This file is generated from `src/skills/catalog.py`. Update the catalog first, then refresh this document.

The reference describes prompt-level Hermes workflow guidance and local evidence expectations. It does not claim hidden Hermes runtime behavior.

Workflow names are kept for compatibility, but each skill declares advisory wrapper guidance for whether Hermes should retain the work directly, ask the user to choose an executor/runtime profile, or prepare a coding handoff for coding-heavy execution.

Exposure is the install contract: `install_visibility: true` surfaces generate `skills/<name>/SKILL.md`; router-only, harness-only, and agent-context surfaces stay routable references unless this document explicitly promotes them.

When wrapper metadata reports `omh_target_topology/v1`, skills bind workflow state to the current Hermes target/thread, adapt only the steps that benefit from multiple targets, and fall back to single-target behavior when the active agent count is one.
`memory_review_card/v1` is separate from `status_card/v1`; `handoff_context_pack/v1` may be attached to executor handoffs only when unresolved conflicts are absent.
`goal_status_card/v1` and `goal_continuation/v1` are goal-execution payloads separate from generic `status_card/v1`; they must name the next action instead of merely summarizing work.

## Skills

### oh-my-hermes

[omh] Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.

- Category: `router`
- Phase: `routing`
- Hermes role: `guide`
- Quality tier: `routing-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Classify requests into Hermes-retained planning/research/interview lanes, executor choice, or prepared coding handoffs; do not execute code.
- Why this exists: `oh-my-hermes` exists to keep Hermes chat routing conservative: it maps plain requests to the right workflow, explains evidence boundaries, and avoids making every keyword look like hidden implementation.
- Use when: Use as the top-level router when a request references oh-my-hermes, asks for the workflow picker, the flagship request-to-handoff path, installed workflows, or ambiguous workflow routing.
- Do not use when:
  - The user already invoked a more specific installed skill and its routing signals are unambiguous.
  - The message is ordinary chat, status acknowledgement, or a question that does not need workflow routing.
  - The wrapper wants to claim execution, review, CI, or merge evidence that no observed artifact provides.
- Strong routing signals: `oh-my-hermes`, `omh`, `./`, `/`, `./o`, `/o`, `./om`, `/om`, `./omh`, `/omh`, `./skills`, `/skills`, `skill picker`, `workflow picker`, `native command`, `command preview`, `fallback card`, `discord command`, `slack command`, `telegram command`, `skill routing`, `workflow routing`, `chat routing`, `request-to-handoff`, `plain request`, `role-owned next action`, `wrapper contract`, `prepared observed`, `evidence boundary`, `상태 기록`, `증거 경계`
- Good example:
  - Prompt: Use OMH request-to-handoff for: safely add a feature to this repo.
  - Expected behavior: Classify the request, name the retained Hermes lane or prepared coding handoff, and expose the observed/prepared evidence boundary.
  - Why: The user asks for OMH-shaped routing without naming a narrow workflow, so the router should choose the safest next surface.
- Bad example:
  - Prompt: omh
  - Expected behavior: Show the workflow picker or ask what the user wants to do next; do not infer a coding workflow.
  - Why: A bare product name is a picker or clarification signal, not implementation evidence.
- Quality bar:
  - Route only from explicit invocation, strong catalog evidence, or a clear workflow-shaped request.
  - Return a clarification or fallback path instead of forcing low-confidence messages into a workflow.
  - Keep users command-agnostic by naming the next UX step rather than shell commands.
  - Expose direct workflow selection without renaming skills or adding an `omh-` prefix to every skill name.
  - Use request-to-handoff as the first path when a plain request needs role, plan, handoff, or status UX.
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
  - Treat partial `./`, `/`, `./o`, or `/om` input as command preview; show one top-level `omh` entry before opening the workflow picker.
  - Use `omh chat native-command` contracts for Discord, Slack, Telegram, or Hermes command/menu registration; treat registration and button rendering as adapter-owned observed evidence.
  - Treat bare `./omh`, `/omh`, `./skills`, or `/skills` as a workflow picker request, not as implementation intent.
  - Ask one concise question when routing signals conflict.
  - Do not claim to override Hermes core routing.

### ralph

[omh] Hermes Ralph workflow: persistent execution with verification and review.

- Category: `execution`
- Phase: `completion`
- Hermes role: `handoff-guide`
- Quality tier: `handoff-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track the selected coding runtime path instead of hiding execution inside chat narration.
- Why this exists: `ralph` exists to keep `execution` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use after scope is concrete and the user wants one owner to continue through implementation and verification.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- Good example:
  - Prompt: ralph: handle a execution request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `ralph` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: ralph: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ralph`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
  - For coding edits, prepare and track selected runtime evidence instead of implying unobserved work happened.
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

[omh] Hermes Ultragoal workflow: file-backed durable goal ledgers.

- Category: `execution`
- Phase: `durable-goals`
- Hermes role: `handoff-guide`
- Quality tier: `checkpoint-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Use Hermes to maintain .omh/goals goal_ledger/v1 state, show goal_status_card/v1 / goal_continuation/v1 next actions, and route coding milestones to the selected runtime profile with only observed runtime evidence.
- Why this exists: `ultragoal` exists for work that can outlive one chat turn: it turns ambition into durable stories, checkpoints, and completion gates so progress can resume without pretending a summary is evidence.
- Use when: Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.
- Do not use when:
  - The request is a single-turn answer, quick diagnosis, or small edit that does not need a durable ledger.
  - Acceptance criteria, current checkpoint, and final gate expectations are too vague to make a goal inspectable.
  - The user expects hidden Hermes code execution rather than explicit executor handoff and observed verification evidence.
- Strong routing signals: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
- Good example:
  - Prompt: $ultragoal add per-skill quality rubrics, regenerate skills, test, and open a PR.
  - Expected behavior: Create or update a goal ledger, split the story into verifiable checkpoints, and close only after generated docs, skills, and tests match.
  - Why: The task has multiple milestones and a final quality gate that should be inspectable across interruptions.
- Bad example:
  - Prompt: $ultragoal what does this one error mean?
  - Expected behavior: Route to diagnosis or a direct answer instead of creating a durable goal.
  - Why: A narrow explanation does not need checkpointed long-running state.
- Quality bar:
  - Keep goal state durable, inspectable, and separate from chat narration.
  - Checkpoint every success, blocker, and final quality gate with fresh evidence.
  - Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.
  - Tell the user the next action through goal_status_card/v1 or goal_continuation/v1 instead of ending with vague follow-up copy.
  - For coding milestones, use prepared runtime handoffs and observed runtime evidence rather than hidden execution claims.
- Required inputs:
  - goal statement
  - acceptance criteria
  - current checkpoint or missing criteria
- Expected outputs:
  - goal_ledger/v1 updates
  - checkpoint evidence
  - goal_completion_gate/v1 result
  - completion or blocker summary
- Artifact expectations:
  - metadata-only .omh/goals ledger
  - goal_status_card/v1 or goal_continuation/v1 wrapper payload
  - runtime run record only for explicitly linked coding milestones
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### loop

[omh] Hermes Loop workflow: loopability assessment, goal interview, research, planning, runtime ticks, verification tiers, handoff, feedback, and resume cycles.

- Category: `goal-loop`
- Phase: `continuous-goal-loop`
- Hermes role: `planner`
- Quality tier: `loop-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep loop orchestration, interviews, research, planning, verification-tier selection, runtime ticks with deterministic queue shapes, loop_engineering/v1 pipeline and building-block status, feedback evaluation, status, and permission-envelope narration in Hermes; prepare selected executor/runtime/worktree/connector/verifier handoffs only when the loop produces concrete work and record completion only from linked goal/runtime evidence.
- Why this exists: `loop` exists for goals whose correct implementation cannot be known upfront but can be discovered through bounded cycles of definition, action, verification, and revision without confusing planned cycles with observed progress.
- Use when: Use when the user explicitly starts a high-level goal that is concrete enough to verify, open-ended enough to require iterative discovery, and should be shaped from task/project/ambition into a bounded loop before cycling through task discovery, distribution, execution, verification tiers, verifier checks, next-task decisions, runtime tick queueing, handoff, feedback, and status until the authority envelope or evidence gate stops it.
- Do not use when:
  - The user asks for one bounded delivery cycle; use `ultraprocess` or `ultragoal` instead.
  - The user gives only a north-star outcome such as revenue, stars, or adoption and has not accepted a bounded first loop goal.
  - The goal is too vague to name an observable problem, next artifact, verification signal, or stop condition.
  - The goal depends mainly on external waiting, adoption, revenue, or community response without observable local next actions.
  - The permission profile does not allow repeated research, handoff, queue, or feedback cycles.
- Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan ultragoal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`
- Good example:
  - Prompt: ./loop make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles.
  - Expected behavior: Start a permission-scoped loop, maintain loop_cycle/v1 state, choose the next concrete task, and keep external outcomes as waiting states.
  - Why: The request is long-horizon and needs repeated discovery, verification, feedback, and resume decisions.
- Bad example:
  - Prompt: ./loop merge this already reviewed one-line README fix.
  - Expected behavior: Use a direct delivery or PR workflow instead of starting a persistent loop.
  - Why: The task is bounded and should stop after merge evidence rather than create ongoing cycles.
- Quality bar:
  - Start with direct user intent such as `./loop` or an explicit long-horizon goal request, then classify it as task, project, ambition, external-wait, or unclear before cycling.
  - Route tiny direct tasks to one-cycle delivery surfaces instead of forcing loop overhead.
  - Reframe a north-star ambition into a bounded arena, observable problem, next loop goal, and next verification without shrinking its ambition.
  - Separate task discovery, distribution, execution, verification, next-task decision, runtime tick queueing, ultragoal/handoff, feedback, waiting, and resume decisions.
  - Expose a permission profile before executor/runtime dispatch, repository mutation, PR, merge, or external publishing.
  - Expose the automation, worktree, skill, connector, and subagent building-block states without treating planned blocks as observed work.
  - Choose workflow patterns such as single-step, fan-out-and-synthesize, adversarial verification, tournament, or triage batch as orchestration metadata only.
  - Keep repeated scaffold shape stable, summarize within bounded budgets, and add verifier lanes only when risk or evidence warrants them.
  - Keep prepared worktree/subagent/connector plans, observed executor work, linked goal completion, and external waiting as distinct evidence states.
  - Use cheap inner-loop checks frequently and expensive outer-loop checks sparingly.
  - Keep the practical small-loop recipe visible: test as stop signal, plan -> execute -> verify, one task at a time.
  - Surface verification_gap, comprehension_debt, and cognitive_surrender as warnings before a loop starts looking self-steering.
- Required inputs:
  - loopability assessment
  - north-star goal summary when present
  - bounded arena
  - observable problem
  - next verification
  - goal reframe
  - success criteria
  - permission profile
  - feedback or wait signal
- Expected outputs:
  - loopability_assessment/v1 task/project/ambition classification
  - loop_start_card/v1 setup prompt
  - loop_cycle/v1 state
  - loop_engineering/v1 pipeline/building-block snapshot
  - loop verification_policy for inner/outer checks
  - loop failure_mode_summary over verification gap, comprehension debt, and cognitive surrender
  - small-loop guidance: test as stop signal, plan -> execute -> verify, one task at a time
  - loop_status_card/v1 next action
  - loop_runtime/v1 queued tick with verification_plan refs
  - loop_queue_handoff/v1 only when permitted
  - executor-neutral handoff only when permitted
  - external-wait or checkpoint boundary
- Artifact expectations:
  - metadata-only .omh/loops loop_cycle/v1 artifact with loopability_assessment/v1
  - loop_engineering/v1 status over automation, worktree, skill, connector, subagent, verification policy, and failure modes
  - loop_runtime/v1 queue entries with context_policy_ref, cost_policy_ref, and verification_plan
  - loop_subagent_result_contract/v1 for prepared subagent handoffs
  - loop_status_card/v1 wrapper payload with loopability_assessment, failure_mode_summary, and small_loop_guidance
  - loop_start_card/v1 wrapper setup card
  - linked goal_ledger/v1 only when completion evidence is required
- Safety rules:
  - Do not treat loop persistence as permission to bypass the selected permission profile.
  - Do not treat a runtime tick as worktree creation, subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or completion evidence.
  - Do not claim goal completion from loop state; require linked goal_ledger/v1 completion evidence.
  - When context or token budget runs out, checkpoint or rely on resumable state instead of pretending the loop is complete.
  - External results such as market response, stars, or adoption are waiting states unless observed evidence is supplied.
  - Do not let unattended loop progress bypass verification; missing or failed verification returns to plan/research or waits for evidence.
  - Do not let comprehension debt or cognitive surrender hide behind green-looking loop status.

### ultraprocess

[omh] Ultra Process - Research - Ralplan - Ultragoal - Code Review - Sync Circle: one PR-ready delivery cycle.

- Category: `process`
- Phase: `single-cycle-plan-to-pr`
- Hermes role: `handoff-guide`
- Quality tier: `process-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep the one-cycle process orchestration, source/codebase research, planning, review framing, docs-sync checks, PR narration, and evidence boundaries in Hermes; convert implementation into a selected executor/runtime handoff such as Codex, Claude Code, OMX/OMO/OMC, another coding agent, or explicit Hermes coding runtime only when the user accepts that owner.
- Why this exists: `ultraprocess` exists to give Hermes one clean plan-to-PR operating cycle: research, reviewed plan, selected implementation handoff, review gate, docs sync, and PR-ready evidence.
- Use when: Use when the user asks Hermes to take a concrete task through one full delivery cycle: research/codebase context, reviewed plan, selected implementation handoff, code review, docs sync when needed, and PR preparation.
- Do not use when:
  - The user wants an open-ended feedback loop or long-horizon campaign; use `loop` instead.
  - The task is still ambiguous enough that a deep interview is required before planning.
  - No repo, product, or delivery surface is available to support a plan-to-PR cycle.
- Strong routing signals: `ultraprocess`, `$ultraprocess`, `./ultraprocess`, `/ultraprocess`, `single-cycle delivery`, `one-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`, `plan implement review docs pr`, `ralplan ultragoal code-review`, `codebase source research planning implementation review docs sync pr`, `docs sync`, `pr-ready`, `prepare a pr`, `sync docs and prepare a pr`, `code-review sync docs and prepare a pr`, `delegate to codex`, `send to codex`, `codex implement`, `codex progress tracking`, `codex session tracking`, `make a pr`, `open a pr`, `끝까지 해줘`, `PR까지`, `계획 구현 리뷰 문서 PR`, `기획 구현 리뷰 문서 PR`, `코드베이스 조사 웹리서치 계획 구현 리뷰 문서 최신화 PR`, `codex로 구현`, `코덱스로 구현`, `codex에게 맡기`, `codex로 맡기`, `코덱스에게 맡기`, `코딩 에이전트에게 맡기`, `구현하게 맡기고 진행상태 추적`, `진행상태 추적`, `진행 상태 추적`, `문서 최신화 PR`
- Good example:
  - Prompt: $ultraprocess research this setup bug, plan the fix, implement, review, sync docs, and prepare a PR.
  - Expected behavior: Run exactly one delivery cycle and report which stages are observed, prepared, or blocked.
  - Why: The user explicitly asks for the full but bounded delivery path ending at PR readiness.
- Bad example:
  - Prompt: $ultraprocess keep improving the project until it becomes popular.
  - Expected behavior: Route to `loop` or ask for a bounded goal rather than promise endless delivery.
  - Why: Popularity and indefinite improvement need long-horizon loop management, not one PR-ready cycle.
- Quality bar:
  - Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.
  - Start with codebase/source research and a ralplan-style decision record before implementation handoff.
  - Use ultragoal or the selected executor/runtime path for implementation, with acceptance criteria and verification commands attached.
  - Run code-review as a gate after implementation evidence exists; review preparation alone is not review evidence.
  - Add docs-specialist sync when public behavior, commands, setup, examples, or claims changed.
  - End with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.
- Required inputs:
  - task statement
  - repo or workspace context
  - executor preference or choose-at-handoff policy
  - verification expectations
- Expected outputs:
  - ralplan-ready context and plan
  - ultragoal or selected executor/runtime handoff
  - code-review gate
  - docs sync checklist
  - single-cycle PR-ready summary with observed evidence and gaps
- Artifact expectations:
  - process checklist or runtime record when a wrapper can observe the stages
  - prepared handoff artifact only after implementation owner selection
  - docs-specialist claim check when public behavior changes
- Safety rules:
  - Do not skip planning when the request is broad, risky, or user-visible.
  - Do not continue into a repeated feedback loop; recommend `loop` when the user wants ongoing cycles.
  - Do not claim implementation, review, CI, merge readiness, or PR creation without observed executor or GitHub evidence.
  - Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.
  - Run docs sync only when behavior, setup, commands, or public claims changed.

### deep-interview

[omh] Hermes Deep Interview workflow: one-question-at-a-time clarification.

- Category: `clarification`
- Phase: `discovery`
- Hermes role: `planner`
- Quality tier: `clarity-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run directly in Hermes or the chat wrapper; produce a clarified brief before any coding handoff is prepared.
- Why this exists: `deep-interview` exists to stop Hermes from guessing through ambiguous product, workflow, or implementation intent; it converts uncertainty into a clarified brief before planning or handoff.
- Use when: Use before planning or execution when requirements are materially ambiguous.
- Do not use when:
  - The request already has concrete scope, acceptance criteria, and verification commands.
  - The missing information is discoverable from the repository or local artifacts without asking the user.
  - The user asked for immediate read-only analysis and the ambiguity does not change the answer.
- Strong routing signals: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `온보딩`, `부드럽게`, `모호한 제품 요청`, `기획자`, `개발자 사이`
- Good example:
  - Prompt: $deep-interview design channel-specific routing, but do not assume what channels mean.
  - Expected behavior: Ask one decision-changing question at a time, then produce goals, non-goals, and acceptance criteria.
  - Why: The request explicitly rejects assumptions and needs product boundaries before implementation.
- Bad example:
  - Prompt: $deep-interview fix this failing test; the traceback and expected behavior are attached.
  - Expected behavior: Proceed to diagnosis or implementation instead of interviewing.
  - Why: The required facts are already available, so more questions would slow the workflow.
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

[omh] Hermes Team workflow: coordinated parallel or sequential work lanes.

- Category: `execution`
- Phase: `coordination`
- Hermes role: `handoff-guide`
- Quality tier: `coordination-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Use Hermes for lane framing and status; implementation lanes should become selected runtime handoff tasks, including Hermes-owned coding when the user chooses that runtime.
- Why this exists: `team` exists to keep `execution` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when multiple independent lanes materially improve throughput or verification.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- Good example:
  - Prompt: team: handle a execution request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `team` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: team: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `team`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Split only independent lanes with explicit ownership and verification boundaries.
  - Keep Hermes as coordinator and status narrator while coding lanes become runtime handoffs with explicit ownership.
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

[omh] Hermes Ultrawork compatibility workflow: bounded parallel delivery guidance.

- Category: `execution`
- Phase: `parallel-delivery`
- Hermes role: `handoff-guide`
- Quality tier: `handoff-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep the workflow name for compatibility, but convert coding lanes into explicit selected runtime handoffs with disjoint scope, verification, review evidence, worker protocol, and worktree guidance.
- Why this exists: `ultrawork` exists to split an accepted implementation plan into independent lanes without letting parallelism blur ownership, verification, worker protocol, worktree isolation, or observed runtime evidence.
- Use when: Use when an accepted implementation plan can be split into independent, reviewable work lanes.
- Do not use when:
  - The work touches the same files or invariants in ways that need one owner.
  - The plan is not accepted, lane boundaries are unclear, or verification commands are missing.
  - The user expects Hermes to secretly execute coding lanes instead of preparing explicit selected-runtime handoffs.
- Strong routing signals: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- Good example:
  - Prompt: $ultrawork implement docs refresh, CLI output polish, and tests as separate accepted lanes.
  - Expected behavior: Create disjoint lane prompts with acceptance criteria, verification commands, and review evidence requirements.
  - Why: The work can be split cleanly and benefits from parallel execution discipline.
- Bad example:
  - Prompt: $ultrawork refactor the central router in five agents at once.
  - Expected behavior: Keep one owner or re-plan boundaries before parallelization.
  - Why: Shared core logic makes parallel edits likely to conflict or hide regressions.
- Quality bar:
  - Require disjoint lane ownership before preparing multiple coding runtime handoffs.
  - Attach acceptance criteria, verification commands, and review expectations to each lane.
  - Keep dispatch, execution, review, CI, and merge status evidence separate.
- Required inputs:
  - accepted plan
  - lane list
  - disjoint file or responsibility scopes
  - verification commands
- Expected outputs:
  - runtime handoff prompts or lane instructions
  - status summary
  - review/CI evidence requirements
- Artifact expectations:
  - prepared coding delegation record per implementation lane when wrappers can record them
- Safety rules:
  - Do not start parallel coding without disjoint ownership boundaries.
  - Keep Hermes responsible for orchestration/status; when Hermes itself is selected for coding, still preserve runtime evidence boundaries.
  - Record unobserved executor work as prepared_not_observed or not_observed.

### web-research

[omh] Hermes Web Research workflow: source-backed current information gathering.

- Category: `research`
- Phase: `current-evidence`
- Hermes role: `researcher`
- Quality tier: `source-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.
- Why this exists: `web-research` exists to make Hermes a careful source-backed research operator: it routes web/current-source requests to evidence gathering, keeps retrieval gaps visible, and prevents search plans from being reported as observed facts.
- Use when: Use when the user needs current web evidence, links, citations, source diversity, or source comparison before planning or handoff.
- Do not use when:
  - The user asks for a full plan-to-PR delivery cycle; use `ultraprocess` or a planning workflow after research instead.
  - The request is purely local repo inspection with no external, current, citation, or source-comparison need.
  - The user needs coding execution, review, CI, or merge evidence rather than research synthesis.
- Strong routing signals: `web-research`, `web research`, `web search`, `search the web`, `internet search`, `latest`, `fresh sources`, `current sources`, `current web evidence`, `source-backed research`, `source search`, `find sources`, `find citations`, `citation check`, `evidence scan`, `source diversity`, `retrieval gap`, `look up`, `lookup`, `investigate`, `research plan`, `웹서치`, `웹 서치`, `웹 검색`, `인터넷 검색`, `검색해줘`, `검색해서`, `최신 자료`, `최신 출처`, `자료 찾아`, `조사`, `근거`, `출처`, `고객 피드백`
- Good example:
  - Prompt: 웹서치해서 최신 자료와 출처를 정리해줘.
  - Expected behavior: Run the Hermes web-research lane, ask for or state source boundaries and freshness, then summarize citations, confidence, and retrieval gaps.
  - Why: The request explicitly asks for web search, current material, and sources without asking for implementation.
- Bad example:
  - Prompt: 웹리서치부터 계획, 구현, 리뷰, 문서, PR까지 한 사이클로 끝내줘.
  - Expected behavior: Route to `ultraprocess` because the user asked for a bounded delivery cycle, not a research-only lane.
  - Why: Research is only one stage of the requested delivery process.
- Quality bar:
  - Ask for the research question, source boundaries, freshness, jurisdiction, and version assumptions before retrieval.
  - Use official or primary sources first when current or external facts matter, then add source diversity when the topic is contested.
  - Separate direct evidence, citation links, retrieval dates, inference, confidence, and residual uncertainty.
  - Name retrieval gaps when Hermes or the wrapper cannot access the web.
  - Summarize research before any coding handoff; research is not implementation evidence.
- Required inputs:
  - research question
  - source boundaries
  - freshness, jurisdiction, or version constraints
- Expected outputs:
  - source-backed synthesis
  - links or citations
  - source-quality notes
  - confidence and residual uncertainty
- Artifact expectations:
  - research notes with source URLs, retrieval dates, and source-quality notes when the wrapper captures them
- Safety rules:
  - Prefer official or primary sources when they can answer the question.
  - Check source diversity and conflicts before summarizing contested or unstable topics.
  - Separate quoted evidence from inference.
  - State retrieval limits, dates, and missing-source gaps for unstable facts.

### research-brief

[omh] Hermes Research Brief workflow: source-backed business research without pretending evidence was fetched.

- Category: `research`
- Phase: `business-brief`
- Hermes role: `researcher`
- Quality tier: `source-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep business research in Hermes; prepare a selected executor/runtime handoff only after a later accepted plan requires code changes.
- Why this exists: `research-brief` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when Hermes should scope a business question, gather or summarize source-backed evidence, and preserve evidence/inference boundaries before strategy or handoff.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`, `market evidence`, `data search`, `source scan`, `자료 조사`, `데이터 서치`, `근거 조사`, `피드백 추세`, `고객 피드백 추세`
- Good example:
  - Prompt: research-brief: handle a research request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `research-brief` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: research-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `research-brief`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - State the research question, source boundaries, and recency assumptions before synthesis.
  - Separate observed sources, source quality, source diversity, inferred trends, and unresolved uncertainty.
  - Use the brief to feed strategy or meeting work without calling it execution evidence.
- Required inputs:
  - business question
  - source boundary
  - recency or market scope
- Expected outputs:
  - evidence table
  - inference summary
  - confidence and uncertainty
- Artifact expectations:
  - research brief or source ledger when the wrapper captures observed sources
- Safety rules:
  - Do not claim sources were fetched unless Hermes or the wrapper observed them.
  - Separate evidence, inference, confidence, source diversity, and missing-source gaps.
  - Route later implementation separately through an accepted plan and coding handoff.

### research-department

[omh] Hermes Research Department workflow pack: prepare Scout, Analyst, and Briefer research operations with source inbox and briefing status boundaries.

- Category: `research`
- Phase: `research-department`
- Hermes role: `researcher`
- Quality tier: `research-ops-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep the research operating model in Hermes. Map Scout to `web-research`/`autoresearch-goal`, Analyst to `research-brief`/`best-practice-research`, and Briefer to `report-package` or meeting/report workflows. Record retrieval, synthesis-tool output, knowledge-store writes, delivery, and verification only from observed evidence.
- Why this exists: `research-department` exists so Hermes users can start complex research-ops patterns without manually designing profiles, cron, knowledge storage, synthesis tooling, and delivery glue, while OMH keeps every runtime claim observed-only.
- Use when: Use when Hermes should turn an ongoing or recurring research request into a prepared Scout -> Analyst -> Briefer workflow with source inbox, knowledge-store and synthesis-tool readiness, and briefing status without claiming research execution.
- Do not use when:
  - The user only needs a one-off current-source lookup; use `web-research`.
  - The user only needs a one-off business synthesis; use `research-brief`.
  - The request is pure scheduling with no source collection or synthesis; use `automation-blueprint`.
  - The user asks for coding implementation; prepare a selected executor/runtime handoff after the research plan is accepted.
- Strong routing signals: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`, `competitor research department`, `market research department`, `paper review`, `weekly paper review`, `research paper review`, `paper research`, `notebooklm research`, `obsidian research vault`, `knowledge store`, `knowledge storage`, `synthesis tool`, `knowledge summarizer`, `research inbox`, `source inbox`, `briefing status`, `리서치 부서`, `리서치 조직`, `리서치 운영`, `수집 합성 브리핑`, `지식 저장소`, `요약 도구`, `경쟁사 리서치 부서`
- Good example:
  - Prompt: research-department 매일 경쟁사와 시장 뉴스를 수집해서 변화가 있으면 브리핑해줘.
  - Expected behavior: Prepare research_department_plan/v1 with Scout/Analyst/Briefer lanes, source inbox buckets, briefing status, knowledge-store and synthesis-tool readiness, and observed-only evidence requirements.
  - Why: The request is recurring, source-backed, and operational; a single research brief would miss the ongoing workflow/status boundary.
- Bad example:
  - Prompt: research-department prove the synthesis tool queried the knowledge base and posted the Slack brief.
  - Expected behavior: Ask for observed synthesis-tool and gateway delivery evidence or mark those states as not_observed.
  - Why: The workflow pack can prepare the operating pattern, but it cannot prove external tool execution or delivery.
- Quality bar:
  - Name topic, source boundaries, cadence, delivery target, knowledge-store destination, and synthesis-tool readiness.
  - Map Scout, Analyst, and Briefer lanes to concrete OMH skills and source inbox buckets.
  - Expose collected, synthesized, briefed, conflict, and verification counts as status, not execution proof.
  - List required evidence before claiming retrieval, synthesis, storage, delivery, or verification.
- Required inputs:
  - topic or watch area
  - source boundaries
  - cadence
  - delivery target
  - knowledge-store preference
  - synthesis-tool preference
- Expected outputs:
  - research_department_plan/v1
  - source_inbox/v1
  - briefing_status/v1
  - not-evidence boundary
- Artifact expectations:
  - research_department_plan/v1 under .omh/research-department/plans when a wrapper or CLI records it
- Safety rules:
  - Do not claim web retrieval, synthesis-tool query, knowledge-store write, cron creation, gateway delivery, or verification from a prepared plan.
  - Keep raw findings, processed notes, briefs, conflicts, and verification needs in separate source inbox buckets.
  - Treat vendor-specific tool names as optional aliases for synthesis-tool and knowledge-store readiness unless observed evidence exists.

### strategy-brief

[omh] Hermes Strategy Brief workflow: options, tradeoffs, recommendation, and decision notes.

- Category: `strategy`
- Phase: `brief`
- Hermes role: `operator`
- Quality tier: `decision-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep strategy synthesis in Hermes; do not create implementation handoff until a decision is accepted and code work is explicit.
- Why this exists: `strategy-brief` exists to keep `strategy` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when Hermes should turn goals and evidence into options, tradeoffs, recommendations, and a decision-ready brief.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `다음 전략`, `전략 정리`, `전략 메모`, `전략 옵션`, `의사결정`, `리더십 회의`
- Good example:
  - Prompt: strategy-brief: handle a strategy request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `strategy-brief` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: strategy-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `strategy-brief`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Name the decision, constraints, options, tradeoffs, and rejected alternatives.
  - Tie recommendations to observed evidence or mark them as assumptions.
  - Keep coding handoff disabled until strategy is accepted and code work is explicit.
- Required inputs:
  - goal
  - known evidence
  - constraints
  - decision owner
- Expected outputs:
  - options
  - tradeoffs
  - recommended direction
  - decision note
- Artifact expectations:
  - strategy brief or decision note when a wrapper captures it
- Safety rules:
  - Do not treat a draft recommendation as an accepted decision.
  - Keep unresolved assumptions visible.
  - Separate strategy from implementation planning unless the user asks for execution.

### meeting-brief

[omh] Hermes Meeting Brief workflow: agenda, prompts, decisions, and record template.

- Category: `meeting`
- Phase: `preparation`
- Hermes role: `operator`
- Quality tier: `facilitation-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run meeting preparation in Hermes; only create follow-up coding handoff from observed decisions or accepted plans.
- Why this exists: `meeting-brief` exists to turn scattered context into a focused agenda, discussion prompts, decision points, and a record template without pretending the meeting already happened.
- Use when: Use when Hermes should prepare a meeting agenda, discussion prompts, decision points, and a record template.
- Do not use when:
  - The user needs observed meeting minutes, decisions, or action items but has not provided notes.
  - The request is strategy synthesis without a meeting audience, agenda, or decision ceremony.
  - The follow-up is implementation work that already has accepted requirements and should become a plan or handoff.
- Strong routing signals: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`, `회의 아젠다`, `아젠다`, `회의 준비`, `논의 질문`, `결정할 것`, `기록 템플릿`
- Good example:
  - Prompt: meeting-brief for a leadership sync on setup UX, plugin bridge defaults, and release risk.
  - Expected behavior: Prepare agenda topics, prompts, decisions needed, and a record template with unknowns marked.
  - Why: The request is preparation for a meeting and should separate prep from observed outcomes.
- Bad example:
  - Prompt: meeting-brief summarize what the team decided yesterday.
  - Expected behavior: Ask for meeting notes or route to an ops/status summary with explicit evidence gaps.
  - Why: A prepared agenda cannot be treated as observed minutes or decisions.
- Quality bar:
  - Turn context into agenda topics, prompts, decisions needed, and a record template.
  - Keep prep distinct from actual meeting minutes or accepted decisions.
  - Identify missing context that would change the meeting structure.
- Required inputs:
  - meeting goal
  - audience
  - known context
  - decision topics
- Expected outputs:
  - agenda
  - discussion prompts
  - decisions needed
  - action-item template
- Artifact expectations:
  - meeting brief or record template when the wrapper captures it
- Safety rules:
  - Do not claim the meeting happened from a prepared agenda.
  - Separate proposed action items from observed decisions.
  - Use a later status or decision record for actual meeting outcomes.

### feedback-triage

[omh] Hermes Feedback Triage workflow: cluster customer signals and choose the next workflow.

- Category: `triage`
- Phase: `feedback`
- Hermes role: `operator`
- Quality tier: `triage-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep feedback triage in Hermes; recommend the next workflow and prepare a selected executor/runtime handoff only after explicit coding intent or accepted plan evidence.
- Why this exists: `feedback-triage` exists to keep customer and community signals from jumping straight into roadmap or coding; it clusters evidence, ranks signals, and chooses the next workflow.
- Use when: Use when Hermes should classify feedback, bug reports, and feature asks before deciding whether research, planning, or coding handoff is needed.
- Do not use when:
  - The request already contains an accepted product decision and asks for implementation.
  - There are no feedback items, source boundary, or product area to classify.
  - The user wants current market research rather than triage of supplied signals.
- Strong routing signals: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`, `payment failure feedback`, `feedback trends`, `payment failure`, `payment failure issue`, `payment failure reports`, `고객 피드백`, `피드백`, `피드백 분류`, `피드백을 모아서`, `결제 실패`, `결제 실패 이슈`, `결제 실패 피드백`, `결제 오류`, `고객 불만`, `버그 제보`, `버그 기능 요청`, `기능 요청`
- Good example:
  - Prompt: feedback-triage these payment failure reports and feature requests before we plan fixes.
  - Expected behavior: Cluster bug signals and feature asks, rank severity or opportunity, and recommend research, planning, or coding as a next workflow.
  - Why: The input is mixed feedback that needs classification before delivery decisions.
- Bad example:
  - Prompt: feedback-triage implement the accepted billing fix now.
  - Expected behavior: Route to planning or coding handoff instead of re-triaging.
  - Why: The decision is already accepted, so triage would add delay without improving evidence.
- Quality bar:
  - Name the source boundary before clustering feedback.
  - Classify signals into bug, feature, research, or strategy follow-up without overclaiming evidence.
  - Recommend the next workflow instead of jumping straight to coding.
- Required inputs:
  - feedback items or summary
  - source boundary
  - product area
- Expected outputs:
  - clusters
  - severity or opportunity ranking
  - next workflow recommendation
- Artifact expectations:
  - feedback triage record when a wrapper captures it
- Safety rules:
  - Do not turn feedback into a roadmap, implementation plan, or coding handoff by default.
  - Separate bug signal, feature ask, severity, opportunity, and missing evidence.
  - Route code changes only after explicit user intent or accepted planning evidence.

### ops-review

[omh] Hermes Ops Review workflow: status, risks, blockers, priorities, and follow-ups.

- Category: `operations`
- Phase: `status-review`
- Hermes role: `operator`
- Quality tier: `status-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep operating review and status narration in Hermes; delegate code fixes only from explicit accepted follow-up items.
- Why this exists: `ops-review` exists to keep `operations` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when Hermes should summarize observed status, risks, blockers, priorities, and follow-up actions for recurring operating work.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`, `운영 리뷰`, `주간 운영`, `상태 리뷰`, `리스크`, `블로커`, `우선순위`, `릴리즈 리스크`
- Good example:
  - Prompt: ops-review: handle a operations request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `ops-review` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: ops-review: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ops-review`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Tie every status claim to observed evidence or mark it as unknown.
  - Separate risks, blockers, priorities, and follow-up owners.
  - Keep code fixes as explicit follow-up handoffs, not implicit ops-review output.
- Required inputs:
  - status evidence
  - scope
  - time window
  - known risks
- Expected outputs:
  - status summary
  - risks
  - blockers
  - priorities
  - follow-up actions
- Artifact expectations:
  - ops review record or status artifact when a wrapper captures it
- Safety rules:
  - Do not infer status from missing evidence.
  - Separate observed facts, risks, blockers, decisions, and follow-up actions.
  - Do not report review, CI, release, or merge readiness from an ops summary alone.

### operating-rhythm

[omh] Hermes Operating Rhythm workflow: meeting minutes, scrum/sprint records, retros, decisions, and follow-up history.

- Category: `operations`
- Phase: `rhythm-history`
- Hermes role: `operator`
- Quality tier: `operations-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep cadence records, minutes scaffolds, decisions, and follow-up history in Hermes; delegate implementation only from separately accepted action items.
- Why this exists: `operating-rhythm` exists so recurring operating work has durable minutes, decisions, and follow-up history without pretending a meeting outcome was observed.
- Use when: Use when Hermes should prepare or maintain recurring operating records such as meetings, scrums, sprint plans, retrospectives, decisions, and follow-ups.
- Do not use when:
  - The user only needs a one-off meeting agenda before the meeting; use `meeting-brief`.
  - The request is a weekly status/risk summary rather than cadence history; use `ops-review`.
  - The user asks for report packaging, PPT outline, or reliability evidence review.
- Strong routing signals: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`, `sprint retrospective`, `retro history`, `decision log`, `action item history`, `회의록 관리`, `회의 히스토리`, `운영 리듬`, `스크럼`, `스프린트 회고`, `결정 기록`, `액션 아이템`
- Good example:
  - Prompt: operating-rhythm 회의록 히스토리 관리하고 스크럼 스프린트 회고를 정리해줘.
  - Expected behavior: Create a prepared operating record with cadence, decisions, action items, and not-evidence markers for missing observed notes.
  - Why: The request is about recurring operating history, not a generic agenda or code handoff.
- Bad example:
  - Prompt: operating-rhythm implement the action items from the retro.
  - Expected behavior: Route implementation to a plan or selected executor/runtime handoff after action items are accepted.
  - Why: Operating records can capture follow-ups, but implementation is a separate observed work stream.
- Quality bar:
  - Name cadence, audience, time window, known notes, and missing evidence before producing a record.
  - Separate agenda/templates from observed minutes, decisions, and action items.
  - Record follow-up ownership only when supplied or explicitly mark it unknown.
- Required inputs:
  - cadence or meeting type
  - audience or participants
  - time window
  - source notes or explicit missing-notes boundary
- Expected outputs:
  - operation artifact
  - decision log
  - action item history
  - observed/prepared boundary
- Artifact expectations:
  - operation_artifact/v1 under .omh/operations when a wrapper or CLI records it
- Safety rules:
  - Do not treat a prepared record as proof that the meeting or scrum happened.
  - Do not mark decisions or action items accepted without supplied notes or owner acknowledgement.
  - Keep implementation follow-ups separate from operating history.

### report-package

[omh] Hermes Report Package workflow: weekly/monthly reports, executive briefs, PPT-ready outlines, and upload packages.

- Category: `reporting`
- Phase: `package-outline`
- Hermes role: `operator`
- Quality tier: `report-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep report narrative, sectioning, and Markdown/JSON outline packaging in Hermes; do not require reliability evidence unless the user asks for a reliability review.
- Why this exists: `report-package` exists to make reporting a first-class operations surface: Hermes can produce clean report and slide outlines while keeping approvals, delivery, and binary deck export as separate evidence.
- Use when: Use when Hermes should turn supplied inputs into a report, executive brief, PPT-ready outline, or upload package without claiming presentation delivery.
- Do not use when:
  - The user needs SLO, incident, or error-budget review; use `reliability-review`.
  - The user asks for a live `.pptx` deck file rather than a PPT-ready outline.
  - The request is meeting minutes, scrum history, or action-item tracking.
- Strong routing signals: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`, `status package`, `ppt outline`, `presentation outline`, `slide outline`, `upload package`, `보고서 패키지`, `주간 보고서`, `월간 보고서`, `경영진 보고`, `리더십 보고`, `PPT`, `피피티`, `슬라이드`, `발표자료`, `업로드 패키지`
- Good example:
  - Prompt: report-package 월간 리더십 보고서 PPT outline 만들어줘.
  - Expected behavior: Prepare a report package with sections, assumptions, missing inputs, and Markdown/JSON outline scope.
  - Why: The request is packaging known information for reporting, not reliability validation or code work.
- Bad example:
  - Prompt: report-package prove our SLO passed and close the incident.
  - Expected behavior: Route to `reliability-review` and require metric or incident evidence.
  - Why: Report packaging cannot satisfy reliability closure evidence.
- Quality bar:
  - Name audience, reporting period, sections, supplied facts, assumptions, and missing data.
  - Keep report packaging independent from reliability review unless explicitly requested.
  - Export only Markdown/JSON outlines unless a separate presentation tool produces a binary deck.
- Required inputs:
  - audience
  - reporting period or scope
  - supplied facts
  - missing data or assumptions
- Expected outputs:
  - report package
  - PPT-ready Markdown or JSON outline
  - assumptions and missing-input list
- Artifact expectations:
  - operation_artifact/v1 report-package artifact when a wrapper or CLI records it
- Safety rules:
  - Do not claim source review completion from a prepared report package.
  - Do not claim stakeholder approval or presentation delivery without observed evidence.
  - Do not couple report packages to SLO, incident, or error-budget evidence by default.

### materials-package

[omh] Hermes Materials Package workflow: decks, PDFs, spreadsheets, documents, HWP, Markdown, and binary export handoffs.

- Category: `materials`
- Phase: `material-plan`
- Hermes role: `operator`
- Quality tier: `material-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep source organization, outline planning, target-format selection, QA ladder, and missing-input review in Hermes; prepare an executor-neutral document-generation handoff only when a binary file is needed.
- Why this exists: `materials-package` exists so Hermes can handle document, deck, spreadsheet, PDF, Keynote, HWP, and Markdown work as a first-class material-processing workflow without becoming a hidden file generator.
- Use when: Use when Hermes should turn source inputs into a material plan for decks, PDFs, spreadsheets, documents, HWP, Markdown, or binary export handoff without claiming file generation.
- Do not use when:
  - The user only needs a weekly/monthly report outline; use `report-package`.
  - The user asks for recurring meeting minutes or scrum history; use `operating-rhythm`.
  - The request is code documentation, README, or project wiki maintenance; use the docs/wiki workflow.
- Strong routing signals: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`, `render qa`, `layout qa`, `pdf`, `pptx`, `keynote`, `keynote deck`, `docx`, `xlsx`, `csv report`, `spreadsheet`, `excel`, `hwp`, `korean hwp`, `proposal document`, `자료 패키지`, `자료 처리`, `자료 생성`, `문서 패키지`, `문서 생성`, `제안서 문서`, `엑셀`, `스프레드시트`, `피디에프`, `PDF`, `한글 문서`, `HWP`, `키노트`, `파일 export`, `파일 생성`, `렌더 QA`
- Good example:
  - Prompt: materials-package 엑셀 매출 리포트를 PDF로 공유할 수 있게 준비해줘.
  - Expected behavior: Create a material plan with xlsx/pdf target formats, source inputs, missing metrics, QA checks, and a generation handoff boundary.
  - Why: The request is about material processing and binary export evidence, not just a text report outline.
- Bad example:
  - Prompt: materials-package prove the PDF was sent to leadership.
  - Expected behavior: Ask for observed delivery evidence or record the delivery as not_observed instead of claiming it happened.
  - Why: A prepared material artifact cannot prove export, approval, or delivery.
- Quality bar:
  - Name audience, source inputs, target formats, outline sections, assumptions, missing inputs, and output owner.
  - Attach format-specific QA expectations before preparing a binary-generation handoff.
  - Record binary export, render QA, formula checks, approvals, and delivery only from observed evidence.
- Required inputs:
  - audience or recipient
  - source inputs
  - target format(s)
  - deadline or delivery context
  - missing data or assumptions
- Expected outputs:
  - material_artifact/v1 plan
  - format-specific QA ladder
  - executor-neutral generation handoff when needed
  - observed export boundary
- Artifact expectations:
  - material_artifact/v1 under .omh/materials when a wrapper or CLI records it
- Safety rules:
  - Do not claim PPTX, PDF, Keynote, DOCX, XLSX, HWP, or upload output without observed file evidence.
  - Do not claim render QA, formula recalculation, approval, or delivery from a prepared material plan.
  - Keep source facts, assumptions, missing inputs, and generated output evidence separate.

### img-summary

[omh] Hermes img-summary workflow: turn meetings, reports, PRs, issues, research, and release notes into source-specific, domain-aware, poster-archetype-aware image-generation-ready visual prompt cards.

- Category: `materials`
- Phase: `visual-prompt-card`
- Hermes role: `operator`
- Quality tier: `visual-card-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep card copy shaping, source-kind selection, language mode, prompt assembly, and evidence narration in Hermes. Use wrapper-reported image generation only as an optional action; record generated image, visual QA, and delivery claims only from visual_observation/v1 evidence.
- Why this exists: `img-summary` exists so Hermes can turn common communication work into provider-neutral image-card prompts while adapting format to the source kind, adapting visual mood, premium background plate, texture, lighting, and camera treatment to the domain, choosing a poster archetype for visual grammar, and keeping generation, QA, and delivery as observed-only wrapper or user evidence.
- Use when: Use when Hermes should shape supplied notes, report material, PR context, issue feedback, research/news, or release notes into a source-specific visual prompt whose mood, premium background plate, material texture, camera treatment, lighting, motifs, and poster design grammar adapt without claiming image generation.
- Do not use when:
  - The user needs a deck, PDF, spreadsheet, HWP, Markdown package, or binary file export plan; use `materials-package`.
  - The user wants a text-only report, leadership brief, or PPT-ready outline; use `report-package`.
  - The user asks OMH to directly generate, inspect, upload, or post an image without a wrapper-supplied observed evidence path.
- Strong routing signals: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image summary card`, `summary image`, `summary card`, `explainer image`, `feature explainer image`, `feature explanation image`, `product explainer image`, `product explainer card`, `infographic`, `one-page infographic`, `workflow image`, `workflow card`, `shareable image`, `explain this as an image`, `make an image explaining`, `vertical card`, `vertical summary image`, `meeting image`, `meeting summary image`, `conversation summary image`, `meeting notes image`, `pr card`, `pr summary card`, `pull request card`, `review card`, `issue card`, `bug triage card`, `feedback card`, `triage card`, `research card`, `report card`, `report summary card`, `report digest card`, `news briefing card`, `competitor-news briefing card`, `briefing card`, `release announcement image`, `release notes image`, `announcement card`, `multilingual img-summary`, `회의록 세로 요약 이미지`, `회의 요약 이미지`, `PR 요약 카드`, `이슈 트리아지 카드`, `버그 트리아지 카드`, `피드백 카드`, `리포트 요약 카드`, `보고서 요약 카드`, `경쟁사 뉴스 브리핑 카드`, `리서치 브리핑 카드`, `릴리즈 노트 발표 이미지`, `업데이트 발표 이미지`, `설명 이미지`, `설명하는 인포그래픽`, `기능 설명 이미지`, `기능 소개 이미지`, `인포그래픽`, `인포그래픽 만들어줘`, `이미지 요약 카드`, `요약 이미지`, `요약 카드`, `카드 이미지`, `공유용 이미지`, `안내 이미지`, `워크플로우 이미지`, `이미지로 설명`, `이미지 하나 만들어줘`
- Good example:
  - Prompt: img-summary make a PR summary card for reviewers.
  - Expected behavior: Prepare visual_prompt_card/v1 with the PR review infographic format, copy mode, generation prompt, negative prompt, and not-evidence boundaries.
  - Why: The request asks for an image-card communication artifact, not a PDF/deck package or hidden image generation.
- Bad example:
  - Prompt: img-summary prove this generated card was posted to Slack.
  - Expected behavior: Ask for visual_observation/v1 delivery evidence or report delivery as not_observed.
  - Why: A prompt card cannot prove generated image, QA, or delivery evidence.
- Quality bar:
  - Pick one canonical source kind: meeting, github_pr, issue_feedback, research_briefing, report_summary, or release_announcement.
  - Use the source-specific format profile instead of forcing every visual into the same grid.
  - Expose the detected `domain_key` so wrappers and users can explain why a domain-specific scene and poster archetype were selected.
  - Adapt the high-fidelity background plate, scene, material texture, depth, lighting, camera treatment, motifs, palette, and composition to the detected domain such as security, commerce, sports, fashion, finance, developer work, or research.
  - Resolve a poster archetype such as Swiss grid, cinematic key-art, editorial magazine, constructivist photomontage, data infographic, product ad, technical brutalist, museum exhibition, sports event, or luxury lookbook, and keep it separate from source kind and domain.
  - Ask image tools to render the domain-specific environment first, then place readable card modules on top; reject flat vector clipart, plain gradients, generic glass cards, color-swapped templates, and low-detail wallpaper.
  - Preserve a stable OMH img-summary format contract: source badge, headline, source-kind subtitle, content modules, evidence footer, and small `OMH generated` mark.
  - Use long_scroll or extended rows when the card needs a document-style vertical canvas with more sections or denser text.
  - Keep visible card text readable and faithful to supplied source or structured sections; do not shrink paragraphs into tiny poster copy.
  - Separate prompt prepared, image generated, visual QA passed, and delivered states.
  - Prefer `img-summary` over `materials-package` only when the request asks for an image, visual card, or summary card.
  - Use materials/report workflows only after an observed generated file needs packaging.
- Required inputs:
  - source kind
  - visual format or auto
  - poster archetype or auto
  - aspect ratio
  - headline or source text
  - audience
  - language mode
  - card sections or supplied source excerpts
- Expected outputs:
  - visual_prompt_card/v1
  - image_generation_setup/v1 when generator capability is missing
  - source-specific visual format
  - detected domain_key
  - domain-aware visual theme
  - poster_archetype/v1
  - poster archetype visual grammar
  - premium background plate, texture, camera, and lighting direction
  - image-safe card copy
  - generation prompt
  - negative prompt
  - quality checks
  - visual evidence boundary
- Artifact expectations:
  - visual_prompt_card/v1 prompt card when prepared
  - image_generation_setup/v1 fallback when image_generation_capability/v1 is unknown or prompt_only
  - visual_observation/v1 only when a wrapper or user records generated image, visual QA, or delivery evidence
- Safety rules:
  - Do not call image providers, LLMs, APIs, or network services from OMH core.
  - Do not claim image generation, visual QA, posting, sharing, attachment, or delivery from a prepared prompt card.
  - Require visual_observation/v1 before claiming generated image, visual QA, or delivery evidence.
  - Raw source text may become only an extractive draft; do not fabricate summaries, owners, decisions, test results, or conclusions.
  - Show `generate_visual_image` only when wrapper context reports image_generation_capability/v1 as connected, and still treat it as wrapper-owned action rather than evidence.
  - When image_generation_capability/v1 is unknown or prompt_only, ask which image tool to use and route to image_generation_setup/v1 instead of pretending generation can start.

### automation-blueprint

[omh] Hermes Scheduled Ops Blueprint workflow: design recurring Hermes operations with schedule, delivery, silence policy, context chain, and prepared-vs-observed status.

- Category: `operations`
- Phase: `scheduled-ops-blueprint`
- Hermes role: `operator`
- Quality tier: `ops-blueprint-gated`
- Exposure: `workflow_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when the user asks for recurring automation or scheduled ops planning.
- Handoff policy: Keep schedule intent, delivery policy, silence rules, context-chain selection, and status narration in Hermes; prepare host automation or no-agent follow-up only after an operator/wrapper records observed runtime evidence.
- Why this exists: `automation-blueprint` exists so Hermes can make recurring operational work feel native and scheduled without OMH becoming a hidden cron runner, transport bot, source retriever, or executor.
- Use when: Use when Hermes should turn a natural recurring/cron-like request into a scheduled ops blueprint without claiming host automation, platform delivery, source retrieval, or no-agent execution.
- Do not use when:
  - The user needs a one-off report or deck; use `report-package` or `materials-package`.
  - The user asks to review incident metrics once; use `reliability-review`.
  - The user needs actual code changes; prepare a selected executor/runtime handoff after the blueprint or plan is accepted.
- Strong routing signals: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`, `recurring ops`, `recurring workflow`, `every morning`, `every day`, `daily digest`, `weekly digest`, `send to slack`, `send to discord`, `post to telegram`, `only if changed`, `silent if nothing changed`, `schedule this`, `매일`, `매주`, `정기`, `예약`, `반복`, `스케줄`, `슬랙`, `디스코드`, `텔레그램`, `보내`, `공유`, `변화 없으면`, `조용히`
- Good example:
  - Prompt: automation-blueprint every morning check competitor news and send a Slack digest only if something changed.
  - Expected behavior: Prepare hermes_ops_blueprint/v1 with schedule intent, Slack delivery policy, silence rule, research/report skills, missing evidence, and next confirmation.
  - Why: The request is recurring, delivery-shaped, and must stay prepared until host automation and gateway delivery are observed.
- Bad example:
  - Prompt: automation-blueprint prove the Slack digest was delivered this morning.
  - Expected behavior: Ask for observed Hermes/gateway delivery evidence or report the delivery as not_observed instead of claiming it happened.
  - Why: A blueprint can prepare the scheduled operation, but it cannot prove runtime execution or delivery.
- Quality bar:
  - Name cadence/timezone uncertainty, delivery target, silence/no-change rule, selected skills, and context chain.
  - Expose whether a no-agent watchdog is a candidate without claiming it exists or ran.
  - List host automation, gateway delivery, source retrieval, and no-agent execution as not evidence until observed.
- Required inputs:
  - recurring request
  - schedule or cadence hint
  - delivery target or current-thread default
  - silence/no-change preference
- Expected outputs:
  - hermes_ops_blueprint/v1 projection
  - schedule/delivery/silence confirmation needs
  - status-card boundary
  - not-evidence list
- Artifact expectations:
  - hermes_ops_blueprint/v1 under .omh/hermes-ops/blueprints when a wrapper or CLI records it
- Safety rules:
  - Do not claim host cron, Hermes automation, gateway delivery, source retrieval, no-agent execution, plugin load, or connector work from a prepared blueprint.
  - Keep scheduled operations as projection metadata until the host runtime supplies observed evidence.
  - Route later coding, material generation, or report delivery into separate accepted handoffs when needed.

### reliability-review

[omh] Hermes Reliability Review workflow: postmortems, SLOs, error budgets, incident follow-ups, and service reliability evidence.

- Category: `reliability`
- Phase: `incident-and-slo-review`
- Hermes role: `operator`
- Quality tier: `reliability-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep incident/SLO/error-budget review in Hermes; prepare remediation handoffs only after an accepted fix direction exists and record closure only from observed evidence.
- Why this exists: `reliability-review` exists to make SRE-style review strict: service reliability claims must point to metrics or references, and remediation remains separate from the review narrative.
- Use when: Use when Hermes should review incident notes, SLOs, error budgets, or service reliability evidence while keeping remediation and closure claims observed.
- Do not use when:
  - The user only needs a generic status report or leadership deck.
  - No service, incident, SLO, metric, or reliability source boundary is available.
  - The request is implementation of remediation rather than review of reliability evidence.
- Strong routing signals: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`, `slo`, `sla`, `error budget`, `service reliability`, `reliability followup`, `remediation tracking`, `sre review`, `장애 리뷰`, `장애 회고`, `포스트모템`, `사후 분석`, `에러버짓`, `에러 버짓`, `서비스 신뢰성`, `신뢰성 검증`, `재발 방지`
- Good example:
  - Prompt: reliability-review 장애 포스트모템과 SLO 에러버짓 상태를 검토해줘.
  - Expected behavior: Prepare a reliability artifact that separates metrics/references, assumptions, missing evidence, and remediation follow-ups.
  - Why: The request is reliability evidence review with closure-sensitive claims.
- Bad example:
  - Prompt: reliability-review make a monthly PPT report for leadership.
  - Expected behavior: Use `report-package` unless the report specifically asks for reliability evidence review.
  - Why: Report packaging and reliability validation are independent operations surfaces.
- Quality bar:
  - Name service, incident/time window, SLO/error-budget target, source references, and missing observations.
  - Separate supplied metrics, incident notes, assumptions, and remediation follow-ups.
  - Keep closure and remediation status unobserved until evidence is supplied.
- Required inputs:
  - service or incident scope
  - time window
  - metric/source references
  - known remediation items or gaps
- Expected outputs:
  - reliability review
  - evidence and missing-evidence list
  - remediation follow-up boundary
- Artifact expectations:
  - operation_artifact/v1 reliability-review artifact when a wrapper or CLI records it
- Safety rules:
  - Do not claim SLO pass, healthy error budget, incident closure, or remediation completion without source, metric, or reference evidence.
  - Do not treat a reliability narrative as verification, review, CI, merge, or deploy evidence.
  - Route code remediation through a separate accepted plan or executor handoff.

### idea-to-deploy

[omh] Hermes Idea-to-Deploy workflow: shape an app idea into decisions, delivery handoff, verification, release, and monitoring status.

- Category: `delivery`
- Phase: `app-delivery-loop`
- Hermes role: `operator`
- Quality tier: `delivery-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep idea shaping, decision gates, planning, release narration, and status in Hermes; prepare selected executor/runtime handoffs only for accepted code work and record deploy/monitoring only from observed operator or wrapper evidence.
- Why this exists: `idea-to-deploy` exists to keep `delivery` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when Hermes should carry a product or app idea through shaping, decision gates, plan acceptance, executor handoff, verification, release readiness, deploy, and monitoring boundaries.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`, `app delivery loop`, `complete product loop`, `end-to-end app operation`, `완제품 루프`, `아이디어부터 배포`, `기획부터 배포`, `출시까지`, `앱 운영 루프`
- Good example:
  - Prompt: idea-to-deploy: handle a delivery request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `idea-to-deploy` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: idea-to-deploy: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `idea-to-deploy`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Name the idea, user value, decision owner, non-goals, and success metric before planning delivery.
  - Expose idea, decision, plan, handoff, verification, release, deploy, and monitor stages as separate status steps.
  - Prepare coding handoffs only after plan acceptance and selected executor/runtime choice.
  - Mark deploy, monitoring, and rollback as unobserved until the wrapper or operator records evidence.
- Required inputs:
  - product idea
  - target user or customer signal
  - success metric
  - repo or app context
- Expected outputs:
  - stage rail
  - decision gates
  - executor handoff criteria
  - verification and deploy/monitor status boundaries
- Artifact expectations:
  - app delivery loop status record when the wrapper captures stage acceptance or observations
- Safety rules:
  - Do not claim implementation, deploy, health checks, rollback, or monitoring happened from a prepared loop.
  - Keep coding, release, and monitoring observations as separate evidence gates.
  - Ask for missing success metric, release scope, or executor choice before preparing a handoff.

### cto-loop

[omh] Hermes CTO Loop workflow: roadmap, PM, technical tradeoffs, risk, delivery, release, and follow-up operating cadence.

- Category: `leadership`
- Phase: `operating-loop`
- Hermes role: `operator`
- Quality tier: `decision-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep CTO/PM-style synthesis, tradeoffs, risk ranking, decision notes, and status in Hermes; convert accepted implementation follow-ups into executor-neutral handoffs.
- Why this exists: `cto-loop` exists to keep `leadership` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when Hermes should run a leadership-style operating loop that turns signals into roadmap decisions, technical tradeoffs, delivery risk, release readiness, and explicit follow-up handoffs.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`, `technical leadership loop`, `leadership operating loop`, `engineering leadership`, `CTO 구조`, `PM 구조`, `로드맵`, `아키텍처 트레이드오프`, `기술 리더십`, `출시 준비`
- Good example:
  - Prompt: cto-loop: handle a leadership request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `cto-loop` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: cto-loop: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `cto-loop`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Separate product priority, architecture tradeoff, delivery risk, release risk, and follow-up owner.
  - Tie recommendations to observed signals or mark assumptions.
  - Record accepted decisions separately from draft recommendations.
  - Prepare executor handoffs only for accepted implementation follow-ups.
- Required inputs:
  - operating signals
  - roadmap or release scope
  - known risks
  - decision owner
- Expected outputs:
  - priority frame
  - architecture tradeoffs
  - delivery risks
  - decision note
  - follow-up handoff candidates
- Artifact expectations:
  - leadership loop record or status summary when a wrapper captures decisions and follow-ups
- Safety rules:
  - Do not treat a CTO loop recommendation as an accepted roadmap decision.
  - Do not imply CTO, PM, QA, Security, or Ops runtime agents exist without observed wrapper evidence.
  - Separate strategy decisions from implementation handoffs and release evidence.

### deploy-and-monitor

[omh] Hermes Deploy-and-Monitor workflow: release checklist, deploy decision, health signals, rollback gate, and post-deploy status.

- Category: `monitoring`
- Phase: `release-ops`
- Hermes role: `operator`
- Quality tier: `release-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep release checklist, health criteria, rollback gates, and status narration in Hermes; record deploy, monitor, incident, or rollback evidence only when the wrapper or operator observes it.
- Why this exists: `deploy-and-monitor` exists to keep `monitoring` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when Hermes should prepare or narrate a release operation with deploy checklist, health signals, rollback criteria, and post-deploy status without pretending to run infrastructure.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`, `health check`, `incident watch`, `release health`, `배포 모니터링`, `배포 감시`, `롤백`, `헬스 체크`, `장애 감시`, `릴리즈 모니터링`
- Good example:
  - Prompt: deploy-and-monitor: handle a monitoring request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `deploy-and-monitor` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: deploy-and-monitor: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `deploy-and-monitor`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Name release scope, target environment, health signals, rollback criteria, and evidence owner.
  - Show pre-deploy, deploy decision, monitor, rollback, and post-deploy record as distinct stages.
  - Mark health and rollback status unknown until observed evidence arrives.
  - Convert fix follow-ups into separate accepted plans or executor handoffs.
- Required inputs:
  - release scope
  - environment
  - health signals
  - rollback owner
- Expected outputs:
  - pre-deploy checklist
  - deploy decision gate
  - monitoring watchlist
  - rollback criteria
  - post-deploy status boundary
- Artifact expectations:
  - release operation status record when the wrapper captures deploy or monitor observations
- Safety rules:
  - Do not claim deployment, health checks, rollback, or incident response happened from a prepared checklist.
  - Keep release readiness, deploy decision, monitor signals, and rollback as separate evidence steps.
  - Route code fixes discovered during monitoring as later executor handoffs.

### ultraqa

[omh] Hermes UltraQA workflow: adversarial QA and fix loops.

- Category: `verification`
- Phase: `qa`
- Hermes role: `reviewer`
- Quality tier: `scenario-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Hermes can design scenarios and report observed results; code fixes discovered by QA should become selected executor/runtime handoffs.
- Why this exists: `ultraqa` exists to keep `verification` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when the task needs adversarial test scenarios, verification, and fix loops.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `장애 상황`, `쿠버네티스 장애`, `적절히 진단`, `검증 체크리스트`, `릴리즈 전 gate`
- Good example:
  - Prompt: ultraqa: handle a verification request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `ultraqa` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: ultraqa: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ultraqa`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
- Quality bar:
  - Generate hostile scenarios from changed behavior and known risk areas.
  - Report pass/fail evidence separately from proposed fixes.
  - Delegate code mutations discovered by QA to the selected coding executor.
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

[omh] Hermes Plan workflow: structured planning before execution.

- Category: `planning`
- Phase: `plan`
- Hermes role: `planner`
- Quality tier: `acceptance-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep planning in Hermes; if the accepted plan requires code edits, prepare a selected executor/runtime handoff after acceptance.
- Why this exists: `plan` exists to keep `planning` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use for structured planning when implementation is not ready to start safely, including feature work that needs a safe plan before handoff.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`, `product triage`, `bug triage`, `issue triage`, `reproduction plan`, `workflow hub`, `coding handoff`, `답할 차례`, `준비할 차례`, `project template`, `재현 계획`, `요구사항 정리`, `작업 허브`, `작업 허브가 필요`, `github pr workflow`, `상태와 다음 행동`, `프로젝트별 운영`
- Good example:
  - Prompt: plan: handle a planning request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `plan` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: plan: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `plan`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes Ralplan workflow: consensus planning with review gates.

- Category: `planning`
- Phase: `reviewed-plan`
- Hermes role: `planner`
- Quality tier: `reviewed-plan-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep consensus planning and review in Hermes; produce explicit selected executor/runtime handoff guidance only after the plan is accepted.
- Why this exists: `ralplan` exists to keep `planning` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when requirements are clear enough for planning but architecture, risks, or tests need review.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`, `dangerous`, `dangerous planning`, `unsafe`, `refactor safety`, `PR로 만들`, `PR로 만들 수 있게`, `위험한 리팩터링`, `리팩터링 위험`, `리스크 있는 리팩터링`, `검증 command`, `리뷰 가능한 단위`
- Good example:
  - Prompt: ralplan: handle a planning request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `ralplan` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: ralplan: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ralplan`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes Code Review workflow: bug-first review with evidence.

- Category: `review`
- Phase: `critique`
- Hermes role: `reviewer`
- Quality tier: `finding-evidence-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to the selected coding executor.
- Why this exists: `code-review` exists to make review bug-first and evidence-grounded: findings must cite concrete files, diffs, commands, or artifacts before any summary or fix proposal.
- Use when: Use for review-shaped requests; findings come first and must cite concrete evidence.
- Do not use when:
  - The user asks to implement the fix rather than review existing code or claims.
  - There is no diff, file set, claim, artifact, or expected behavior to review.
  - The request is broad product critique, strategy, or planning rather than code or evidence review.
- Strong routing signals: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`, `evidence audit`, `README claim`, `what actually happened`, `릴리즈 전`, `실제 코드와 맞는가`, `실제로 뭐 했는지`, `검증된 결과`
- Good example:
  - Prompt: $code-review check this PR for install/update UX regressions and missing tests.
  - Expected behavior: Lead with ranked findings, cite concrete evidence, then list open questions and test gaps.
  - Why: The task is explicitly review-shaped and has a behavioral risk surface.
- Bad example:
  - Prompt: $code-review add the missing setup flag and commit it.
  - Expected behavior: Route implementation to a selected executor/runtime after review findings are established.
  - Why: Review can identify the issue, but code mutation is a separate execution step.
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

[omh] Hermes AI slop cleaner workflow: behavior-preserving cleanup.

- Category: `maintenance`
- Phase: `cleanup`
- Hermes role: `handoff-guide`
- Quality tier: `regression-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Use Hermes to define cleanup scope and regression checks; route behavior-preserving edits to the selected coding runtime once tests are clear.
- Why this exists: `ai-slop-cleaner` exists to keep `maintenance` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use for behavior-preserving cleanup with tests before and after edits.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `behavior-preserving refactor`, `risk analysis`, `refactor workflow`, `legacy refactor`, `리팩터링`, `리팩토링`, `위험 분석`, `변경 범위 제한`, `회귀 테스트`
- Good example:
  - Prompt: ai-slop-cleaner: handle a maintenance request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `ai-slop-cleaner` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: ai-slop-cleaner: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ai-slop-cleaner`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for bounded official/upstream best-practice research.

- Category: `research`
- Phase: `evidence`
- Hermes role: `researcher`
- Quality tier: `source-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run as Hermes-side evidence gathering; hand coding to the selected executor/runtime only after source-backed guidance is summarized.
- Why this exists: `best-practice-research` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when correctness depends on current official or upstream guidance.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- Good example:
  - Prompt: best-practice-research: handle a research request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `best-practice-research` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: best-practice-research: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `best-practice-research`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for durable research-goal execution.

- Category: `research`
- Phase: `durable-research`
- Hermes role: `researcher`
- Quality tier: `validator-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Keep durable research in Hermes-managed artifacts; do not convert to executor handoff unless the research produces an accepted coding task.
- Why this exists: `autoresearch-goal` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use for validator-gated research that needs durable artifacts.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- Good example:
  - Prompt: autoresearch-goal: handle a research request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `autoresearch-goal` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: autoresearch-goal: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `autoresearch-goal`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for measurable performance-goal execution.

- Category: `optimization`
- Phase: `measurement`
- Hermes role: `tracker`
- Quality tier: `measurement-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Hermes can own baselines, benchmark plans, and status; optimization code changes should be selected executor/runtime handoffs.
- Why this exists: `performance-goal` exists to keep `optimization` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use when the goal is measurable performance improvement with evaluator evidence.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- Good example:
  - Prompt: performance-goal: handle a optimization request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `performance-goal` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: performance-goal: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `performance-goal`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for maintaining a project-local markdown wiki.

- Category: `knowledge`
- Phase: `capture`
- Hermes role: `memory-keeper`
- Quality tier: `knowledge-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run directly in Hermes as knowledge capture unless the note reveals a separate coding task.
- Why this exists: `wiki` exists to keep `knowledge` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use to capture durable project knowledge in markdown artifacts.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `wiki`, `project wiki`, `memory`, `notes`
- Good example:
  - Prompt: wiki: handle a knowledge request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `wiki` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: wiki: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `wiki`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for consulting an external advisor when configured.

- Category: `review`
- Phase: `external-advice`
- Hermes role: `reviewer`
- Quality tier: `evidence-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.
- Why this exists: `ask` exists to keep `review` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use only when an external advisor is configured and would materially improve the answer.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- Good example:
  - Prompt: ask: handle a review request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `ask` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: ask: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ask`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for ending active workflow state cleanly.

- Category: `operator`
- Phase: `state-cleanup`
- Hermes role: `tracker`
- Quality tier: `evidence-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run directly in Hermes/runtime state; never delegate cancellation to a coding executor.
- Why this exists: `cancel` exists to keep `operator` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use to cleanly end active adapted workflow state.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `cancel`, `$cancel`, `stop`, `abort`
- Good example:
  - Prompt: cancel: handle a operator request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `cancel` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: cancel: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `cancel`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for managing local skills.

- Category: `operator`
- Phase: `skill-management`
- Hermes role: `tracker`
- Quality tier: `evidence-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Use Hermes for inventory and guidance; delegate only repository code changes to the selected coding executor.
- Why this exists: `skill` exists to keep `operator` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.
- Use when: Use for local skill listing, search, add, remove, or edit tasks.
- Do not use when:
  - The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
  - The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- Strong routing signals: `skill`, `$skill`, `skills`, `manage skills`
- Good example:
  - Prompt: skill: handle a operator request that needs explicit evidence boundaries and a clear stop condition.
  - Expected behavior: Run `skill` only after naming the target, evidence boundary, and stop condition.
  - Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.
- Bad example:
  - Prompt: skill: treat casual chat or unaccepted work as if this workflow already produced verified results.
  - Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `skill`.
  - Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.
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

[omh] Hermes adaptation for diagnosing oh-my-hermes installation health.

- Category: `operator`
- Phase: `diagnostics`
- Hermes role: `tracker`
- Quality tier: `evidence-gated`
- Exposure: `direct_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.
- Handoff policy: Run directly as local health inspection; propose executor work only when a repo fix is required.
- Why this exists: `doctor` exists to turn confusing install/setup states into grouped, local health evidence and the next repair action without treating a check as a fix.
- Use when: Use to diagnose OMH installation and Hermes config registration.
- Do not use when:
  - The user is asking for a general product explanation rather than local health diagnostics.
  - The requested change is a repository bug fix, not an installed-environment check.
  - The wrapper wants to claim Hermes reload, skill execution, or plugin behavior that was not observed.
- Strong routing signals: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- Good example:
  - Prompt: doctor after omh update says setup is next but Hermes skills still look stale.
  - Expected behavior: Inspect managed skills, Hermes registration, runtime state, and next repair action with explicit proof boundaries.
  - Why: The issue is local installation health and needs grouped diagnostic evidence.
- Bad example:
  - Prompt: doctor implement a new uninstall command UX.
  - Expected behavior: Route to planning or implementation instead of health diagnostics.
  - Why: That is product development work, not a local health check.
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

### github-event-ops

[omh] Hermes GitHub event operations workflow: route PR, issue, CI, and review webhook events into triage, review, or fix handoff cards.

- Category: `github-ops`
- Phase: `event-routing`
- Hermes role: `operator`
- Quality tier: `workflow-surface-gated`
- Exposure: `router_only`
- Install visibility: `false`
- Docs visibility: `compatibility_reference`
- Compatibility alias: `true`
- Preferred usage: Prefer natural-language Hermes routing into the GitHub event ops playbook/harness instead of showing this as a primary skill picker item.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `github-event-ops` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when Hermes receives or is asked to reason about GitHub PR, issue, review, or CI events and must choose review, triage, or fix-handoff without claiming a bot ran.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `github-event-ops`, `github event ops`, `pr opened`, `ci failed`, `issue opened`, `pull request webhook`, `github webhook`, `auto review pr`, `label issue`, `ci analysis`, `깃허브`, `이슈 라벨`, `pr 리뷰`, `ci 실패`
- Good example:
  - Prompt: github-event-ops PR opened with failing CI; triage whether this needs review or fix handoff.
  - Expected behavior: Produce `prepare_github_event_ops_card` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: github-event-ops prove the issue was labelled and CI was rerun.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - github-event-ops/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - github-event-ops/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - A GitHub event ops card is not webhook delivery, GitHub API mutation, review completion, label application, CI rerun, or fix execution evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### agent-board

[omh] Hermes agent board workflow: coordinate multiple Hermes profiles or agents with task, handoff, heartbeat, blocker, and completion states.

- Category: `agent-coordination`
- Phase: `board-status`
- Hermes role: `tracker`
- Quality tier: `workflow-surface-gated`
- Exposure: `agent_context`
- Install visibility: `false`
- Docs visibility: `agent_context_reference`
- Compatibility alias: `true`
- Preferred usage: Use as Hermes agent/context guidance for board-shaped collaboration; keep direct invocation compatibility only for existing references.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `agent-board` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when multiple Hermes profiles, agents, or targets need a board-shaped status contract for collaborative work.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `agent-board`, `agent board`, `kanban`, `multi agent board`, `hermes profiles`, `task board`, `heartbeat`, `blocker`, `handoff board`, `칸반`, `여러 에이전트`, `작업 보드`
- Good example:
  - Prompt: agent-board coordinate PM, CTO, QA, and release agents on this launch checklist.
  - Expected behavior: Produce `prepare_agent_board_card` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: agent-board mark the other agent complete without an observed heartbeat or result.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - agent-board/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - agent-board/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - An agent board card is not proof that another Hermes agent accepted, executed, heartbeat-ed, or completed work unless target-specific evidence exists.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### memory-curation-review

[omh] Hermes memory curation workflow: review stale, conflicting, duplicate, or risky memories and skill notes through approve/reject/update actions.

- Category: `memory`
- Phase: `curation-review`
- Hermes role: `memory-keeper`
- Quality tier: `workflow-surface-gated`
- Exposure: `workflow_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when the user asks to review stale, duplicate, or conflicting memory and skill context.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `memory-curation-review` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when Hermes memory, USER/MEMORY files, or accumulated skill guidance needs human-approved cleanup.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `memory-curation-review`, `memory curation`, `memory review`, `memory inspect`, `memory context review`, `context review`, `context cleanup`, `context curation`, `curate memory`, `stale memory`, `conflicting memory`, `duplicate skill`, `MEMORY.md`, `USER.md`, `기억 점검`, `기억 정리`, `기억하는 맥락`, `메모리 정리`, `맥락 점검`, `맥락 정리`, `등록된 맥락`, `헤르메스 기억`, `중복 스킬`
- Good example:
  - Prompt: memory-curation-review inspect stale project memories and ask me what to keep.
  - Expected behavior: Produce `prepare_memory_curation_review` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: memory-curation-review silently delete all conflicting memories.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - memory-curation-review/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - memory-curation-review/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - A memory curation review is not Hermes internal memory, MEMORY.md, USER.md, or skill-file modification evidence until an approved write is observed.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### gateway-intent-card

[omh] Hermes gateway intent workflow: normalize Discord, Slack, Telegram, and other gateway sessions into origin, thread, delivery, silent, attachment, and status-update policy.

- Category: `gateway`
- Phase: `intent-card`
- Hermes role: `guide`
- Quality tier: `workflow-surface-gated`
- Exposure: `router_only`
- Install visibility: `false`
- Docs visibility: `compatibility_reference`
- Compatibility alias: `true`
- Preferred usage: Prefer wrapper or Hermes natural-language routing into gateway intent policy instead of exposing this as a primary user skill.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `gateway-intent-card` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when Hermes needs platform-neutral gateway policy for a chat session, thread, delivery target, attachment, or status update.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `gateway-intent-card`, `gateway intent`, `discord thread`, `slack thread`, `telegram delivery`, `session delivery`, `silent update`, `attachment policy`, `status update policy`, `게이트웨이`, `디스코드`, `슬랙`, `텔레그램`
- Good example:
  - Prompt: gateway-intent-card route this Discord thread update silently unless action is needed.
  - Expected behavior: Produce `prepare_gateway_intent_card` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: gateway-intent-card prove the Telegram attachment was sent.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - gateway-intent-card/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - gateway-intent-card/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - A gateway intent card is not platform login, message send, thread mutation, attachment upload, or delivery evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### executor-runtime-readiness

[omh] Hermes executor runtime readiness workflow: compare Codex, Claude Code, Hermes coding, and oh-my runtimes by available tools, missing tools, and handoff mode.

- Category: `executor-readiness`
- Phase: `runtime-selection`
- Hermes role: `handoff-guide`
- Quality tier: `workflow-surface-gated`
- Exposure: `harness_only`
- Install visibility: `false`
- Docs visibility: `harness_reference`
- Compatibility alias: `true`
- Preferred usage: Use as a readiness harness/status surface when Hermes needs to compare executor/runtime options before handoff.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `executor-runtime-readiness` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when a user may choose Codex, Claude Code, Hermes coding, or another runtime and needs tool/credential gaps before handoff.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `executor-runtime-readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `executor tools`, `missing tools`, `handoff mode`, `runtime migration`, `omx`, `omc`, `omo`, `코덱스`, `클로드 코드`, `실행 런타임`
- Good example:
  - Prompt: executor-runtime-readiness can this task run in Codex, Claude Code, or Hermes coding?
  - Expected behavior: Produce `prepare_executor_runtime_readiness` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: executor-runtime-readiness claim Codex already started the session.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - executor-runtime-readiness/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - executor-runtime-readiness/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - Runtime readiness is not executor dispatch, plugin load, tool invocation, repository mutation, review, CI, or merge evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### deliverable-package

[omh] Hermes deliverable package workflow: track PPT, PDF, XLSX, DOCX, HWP, Markdown, and attachments through prepared, generated, QA, approved, and attached states.

- Category: `deliverables`
- Phase: `package-status`
- Hermes role: `operator`
- Quality tier: `workflow-surface-gated`
- Exposure: `workflow_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when the user asks for file deliverable packaging and attachment lifecycle status.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `deliverable-package` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when Hermes should prepare, request generation, QA, and report attachment status for user-visible file deliverables.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `deliverable-package`, `deliverable mode`, `file attachment`, `attach file`, `attachment status`, `file delivery`, `file deliverable status`, `generated file`, `자료`, `첨부`, `첨부 상태`, `전달 상태`
- Good example:
  - Prompt: deliverable-package turn this research into PPT and PDF with attachment status.
  - Expected behavior: Produce `prepare_deliverable_package` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: deliverable-package claim the PDF was attached without observed file evidence.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - deliverable-package/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - deliverable-package/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - A deliverable package card is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### voice-operator

[omh] Hermes voice operator workflow: turn short voice or mobile commands into clarify, plan, status, handoff, or confirmation actions.

- Category: `accessibility`
- Phase: `voice-routing`
- Hermes role: `guide`
- Quality tier: `workflow-surface-gated`
- Exposure: `agent_context`
- Install visibility: `false`
- Docs visibility: `agent_context_reference`
- Compatibility alias: `true`
- Preferred usage: Use as Hermes voice/mobile context guidance that normalizes short commands before choosing a concrete workflow.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `voice-operator` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when Hermes receives terse voice/mobile-style requests and should produce concise clarification, plan, or status UX.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `voice-operator`, `voice operator`, `voice-first`, `mobile command`, `short command`, `spoken request`, `accessibility`, `hands free`, `음성`, `모바일`, `접근성`, `짧은 명령`
- Good example:
  - Prompt: voice-operator 'release before lunch, check risky parts' from mobile.
  - Expected behavior: Produce `prepare_voice_operator_card` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: voice-operator assume the user approved a destructive action from a vague voice note.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - voice-operator/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - voice-operator/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - A voice operator card is not speech recognition, mobile notification delivery, platform action, or accepted execution evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### toolbelt-readiness

[omh] Hermes toolbelt readiness workflow: check which MCP servers, CLIs, APIs, credentials, and connectors a workflow needs before claiming it can run.

- Category: `tools`
- Phase: `readiness-check`
- Hermes role: `tracker`
- Quality tier: `workflow-surface-gated`
- Exposure: `harness_only`
- Install visibility: `false`
- Docs visibility: `harness_reference`
- Compatibility alias: `true`
- Preferred usage: Use as a readiness harness when Hermes needs to show missing MCP, CLI, API, credential, or connector requirements.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `toolbelt-readiness` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when a workflow depends on MCP, CLI, API credentials, or connectors and Hermes must show installed, missing, optional, and unsafe tools.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `toolbelt-readiness`, `mcp readiness`, `tool readiness`, `connector readiness`, `needed mcp`, `api credential`, `missing cli`, `toolbelt`, `외부 도구`, `mcp`, `커넥터`, `credential`
- Good example:
  - Prompt: toolbelt-readiness what MCP or CLI tools do I need for weekly Linear and GitHub triage?
  - Expected behavior: Produce `prepare_toolbelt_readiness` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: toolbelt-readiness claim Gmail access works without an observed credential check.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - toolbelt-readiness/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - toolbelt-readiness/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - A toolbelt readiness card is not MCP server installation, credential validation, API access, connector invocation, or successful workflow execution evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### ops-observability-card

[omh] Hermes ops observability workflow: report wrapper-safe token, cost, latency, run history, queue, and failure-mode telemetry boundaries.

- Category: `observability`
- Phase: `telemetry-card`
- Hermes role: `tracker`
- Quality tier: `workflow-surface-gated`
- Exposure: `harness_only`
- Install visibility: `false`
- Docs visibility: `harness_reference`
- Compatibility alias: `true`
- Preferred usage: Use as a telemetry/status harness for token, cost, latency, run history, and failure-mode boundaries.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `ops-observability-card` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when automation, loops, gateway work, or executor handoffs need a safe status card for cost, latency, token, history, and failure-mode visibility.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `ops-observability-card`, `observability card`, `cost telemetry`, `latency telemetry`, `token telemetry`, `run history`, `loop telemetry`, `failure mode`, `monitor tokens`, `비용`, `토큰`, `지연시간`, `관측성`
- Good example:
  - Prompt: ops-observability-card show token, cost, latency, and last run status for this loop.
  - Expected behavior: Produce `prepare_ops_observability_card` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: ops-observability-card claim exact provider billing from local estimates.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - ops-observability-card/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - ops-observability-card/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - An ops observability card is not billing truth, provider quota truth, complete tracing, performance proof, or successful workflow completion evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

### agent-ops-review

[omh] Hermes agent ops review workflow: help a manager inspect AI-agent research, coding, review, status, blockers, quality gates, and throughput levers.

- Category: `operator`
- Phase: `manager-review`
- Hermes role: `tracker`
- Quality tier: `workflow-surface-gated`
- Exposure: `workflow_skill`
- Install visibility: `true`
- Docs visibility: `primary_workflow_skill`
- Compatibility alias: `false`
- Preferred usage: Use as an installed Hermes workflow skill when a manager wants quality, blockers, next actions, and throughput guidance for AI-agent work.
- Handoff policy: Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.
- Why this exists: `agent-ops-review` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.
- Use when: Use when Hermes should explain AI-agent work from a manager/operator perspective: quality gates, progress, blockers, next actions, and throughput opportunities across research, coding, review, and status.
- Do not use when:
  - The request is already handled by a narrower explicit skill with stronger evidence.
  - The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
  - The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- Strong routing signals: `agent-ops-review`, `agent ops review`, `agent productivity`, `operator productivity`, `manager view`, `quality dashboard`, `throughput review`, `agent work quality`, `coding progress quality`, `research coding review status`, `ai agent manager`, `third-party manager`, `관리자 입장`, `작업 생산량`, `처리량`, `품질 퀄리티`, `작업 품질`, `진행상황`, `리서치 코딩 리뷰`
- Good example:
  - Prompt: agent-ops-review show me quality, blockers, and throughput for AI-agent research, coding, and review work.
  - Expected behavior: Produce `prepare_agent_ops_review` with required context, wrapper actions, and not-evidence boundaries.
  - Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.
- Bad example:
  - Prompt: agent-ops-review claim Codex finished and CI passed because a handoff exists.
  - Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
  - Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.
- Quality bar:
  - Name the user-facing workflow objective, required context, next action, and stop condition.
  - Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
  - Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Required inputs:
  - user request
  - target context
  - delivery or status expectation
  - known missing evidence
- Expected outputs:
  - agent-ops-review/v1 card or guidance
  - next action
  - prepared-vs-observed boundary
- Artifact expectations:
  - agent-ops-review/v1 metadata-only runtime or wrapper card when recorded
- Safety rules:
  - An agent ops review card is not source retrieval, executor dispatch, coding progress, implementation, review, verification, CI, merge-readiness, merge, platform delivery, provider billing, or live runtime telemetry evidence.
  - Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

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
  - `show_prompt_handoff`
  - `copy_prompt_handoff`
  - `show_runtime_handoff`
  - `show_coding_team_path`
  - `start_runtime`
  - `start_hermes_coding`
  - `prepare_worktree`
  - `start_team`
  - `start_swarm`
  - `record_runtime_observation`
  - `choose_executor`
  - `send_to_executor`
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
  - Use summary-only rejection when a goal_completion_gate/v1 blocks completion.
  - Surface continue_goal, show_status, record_checkpoint, record_blocker, or record_completion as the next action.
  - Run final verification and review gates before reporting a goal complete.
- Inputs:
  - goal statement
  - acceptance criteria
  - current checkpoint
  - blocked or pending stories
  - linked runtime run ids when coding evidence is explicitly required
- Outputs:
  - goal_ledger/v1 updates
  - checkpoint evidence
  - goal_completion_gate/v1 result
  - goal_status_card/v1 or goal_continuation/v1 next action
- Stop conditions:
  - current goal is complete or explicitly blocked
  - checkpoint evidence is recorded
  - completion gate is ready before final completion copy
- Verification:
  - compare artifacts against acceptance criteria
  - record fresh evidence before completion
  - inspect explicitly linked runtime runs before treating coding work as observed
- Evidence ladder:
  - `goal_created`
  - `story_started`
  - `checkpoint_recorded`
  - `quality_gate_recorded`
  - `goal_closed`
- Wrapper actions:
  - `continue_goal`
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
  - Prepared or unlinked runtime artifacts cannot satisfy a coding-linked goal unless the goal explicitly references that run.
  - Intermediate checkpoints cannot replace final verification and review evidence.
- Fallback: If Hermes has no goal tool, use a local checklist or file-backed ledger and still name the next action.

### planning

Turn clarified requirements into an execution-ready plan with tradeoffs and tests.

- Use when: Use before implementation when architecture, sequencing, or validation shape matters.
- Quality tier: `acceptance-gated`
- Quality bar:
  - Make goals, non-goals, decision drivers, options, risks, and test strategy explicit.
  - Record at least one rejected option and why it lost before presenting the preferred path.
  - Tie every acceptance criterion to a validation command, artifact, or explicit manual evidence gap.
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
  - `option_tradeoffs_recorded`
  - `test_strategy_recorded`
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
  - Scope the research question, source boundaries, recency, and jurisdiction or version assumptions before retrieval.
  - Use official or primary sources first when they can answer the question.
  - Record source quality, source diversity, conflicting evidence, and retrieval gaps before synthesis.
  - Separate source evidence, citation links, inference, confidence, and retrieval limits.
  - Record dates or version boundaries for unstable facts.
- Inputs:
  - research question
  - source boundaries
  - freshness, jurisdiction, version, or environment constraints
- Outputs:
  - source-backed synthesis
  - links or citations
  - source-quality notes
  - confidence and residual uncertainty
- Stop conditions:
  - claims are source-backed
  - source diversity is checked when relevant
  - retrieval limits and dates are explicit
- Verification:
  - prefer official or primary sources
  - check source diversity and conflicts
  - separate evidence from inference
- Evidence ladder:
  - `research_question_scoped`
  - `source_boundaries_recorded`
  - `primary_sources_checked`
  - `source_diversity_checked`
  - `conflicts_checked`
  - `evidence_synthesized`
  - `uncertainty_recorded`
- Wrapper actions:
  - `show_sources`
  - `ask_followup`
  - `record_source`
  - `prepare_plan`
- Artifact events:
  - `research_started`
  - `source_boundary_recorded`
  - `source_checked`
  - `synthesis_recorded`
- Delegation expectation: Record a research lane only when Hermes or the wrapper exposes source/research evidence; otherwise summarize retrieval limits explicitly.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Research synthesis is not implementation evidence.
  - Unavailable web access must be reported as a retrieval gap.
  - A source plan is not observed source retrieval until URLs, citations, or supplied source notes are recorded.
- Fallback: If web access is unavailable, state the retrieval gap and fall back to best available local evidence.

### business-research

Prepare source-backed business research briefs with evidence and inference boundaries.

- Use when: Use when a business, market, customer, or operational question needs source-scoped research before strategy, meetings, or handoff.
- Quality tier: `source-gated`
- Quality bar:
  - Scope the business question and source boundary before synthesis.
  - Separate observed sources, source quality, source diversity, inferred trends, confidence, and uncertainty.
  - Feed strategy or meeting work without treating the research brief as execution evidence.
- Inputs:
  - business question
  - source boundary
  - recency or market scope
- Outputs:
  - evidence table
  - inference summary
  - confidence and residual uncertainty
- Stop conditions:
  - source boundaries are explicit
  - evidence and inference are separated
  - uncertainty is recorded
- Verification:
  - check source quality
  - record missing-source gaps
  - separate observed evidence from synthesis
- Evidence ladder:
  - `business_question_scoped`
  - `source_boundary_recorded`
  - `source_quality_recorded`
  - `source_evidence_recorded`
  - `business_synthesis_recorded`
  - `uncertainty_recorded`
- Wrapper actions:
  - `show_sources`
  - `ask_followup`
  - `prepare_strategy_brief`
  - `show_status`
- Artifact events:
  - `business_research_scoped`
  - `business_source_checked`
  - `business_synthesis_recorded`
- Delegation expectation: Record business research only when Hermes or the wrapper observes sources or captures a research brief.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A research brief is not proof that sources were fetched unless source evidence is observed.
  - Research synthesis is not a decision, implementation, or verification result.
- Fallback: If sources are not available, label the result as a research plan or local-context synthesis rather than observed research.

### strategy-synthesis

Turn goals and evidence into strategy options, tradeoffs, and decision-ready notes.

- Use when: Use when the request asks for strategy, recommendations, decision notes, or leadership-ready synthesis.
- Quality tier: `decision-gated`
- Quality bar:
  - Name the decision, drivers, options, tradeoffs, recommendation, and assumptions.
  - Keep draft recommendations separate from accepted decisions.
  - Convert implementation follow-ups into explicit later plans or handoffs.
- Inputs:
  - goal
  - evidence summary
  - constraints
  - decision owner
- Outputs:
  - options
  - tradeoffs
  - recommendation
  - decision note
- Stop conditions:
  - decision scope is explicit
  - tradeoffs are named
  - assumptions and follow-ups are recorded
- Verification:
  - compare options
  - tie recommendation to evidence
  - record rejected alternatives
- Evidence ladder:
  - `decision_scope_recorded`
  - `options_recorded`
  - `tradeoffs_recorded`
  - `recommendation_recorded`
  - `decision_status_recorded`
- Wrapper actions:
  - `show_brief`
  - `revise_brief`
  - `record_decision`
  - `show_status`
- Artifact events:
  - `strategy_scope_recorded`
  - `options_recorded`
  - `decision_note_recorded`
- Delegation expectation: Record strategy synthesis as Hermes-retained work; record execution only after a later accepted handoff is observed.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A strategy brief is not an accepted decision.
  - A recommendation is not implementation, review, CI, or merge evidence.
- Fallback: If decision authority or evidence is missing, produce assumptions and next questions instead of a final decision.

### meeting-facilitation

Prepare agendas, discussion prompts, decisions, and record templates.

- Use when: Use when the request asks Hermes to prepare a meeting, agenda, discussion guide, or follow-up record template.
- Quality tier: `facilitation-gated`
- Quality bar:
  - Prepare agenda topics, prompts, decisions needed, and a record template from available context.
  - Keep proposed agenda and action items separate from observed meeting outcomes.
  - Ask for missing context that would change participants, decisions, or timing.
- Inputs:
  - meeting goal
  - audience
  - context
  - decision topics
- Outputs:
  - agenda
  - discussion prompts
  - decisions needed
  - record template
- Stop conditions:
  - agenda is coherent
  - decisions needed are explicit
  - actual outcomes remain unobserved
- Verification:
  - check missing context
  - separate prep from outcomes
  - include record template
- Evidence ladder:
  - `meeting_goal_scoped`
  - `agenda_recorded`
  - `discussion_prompts_recorded`
  - `decisions_needed_recorded`
  - `record_template_ready`
- Wrapper actions:
  - `show_agenda`
  - `revise_brief`
  - `record_decision`
  - `show_status`
- Artifact events:
  - `meeting_context_scoped`
  - `agenda_recorded`
  - `record_template_recorded`
- Delegation expectation: Record meeting prep only as prepared content unless observed meeting notes or decisions are supplied.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared agenda is not evidence that a meeting happened.
  - Draft action items are not observed decisions.
- Fallback: If the meeting already happened, ask for observed notes before treating decisions as outcomes.

### customer-insight-triage

Cluster customer feedback and choose the next workflow without defaulting to coding.

- Use when: Use when feedback, bugs, feature asks, or customer signals need classification before planning or implementation.
- Quality tier: `triage-gated`
- Quality bar:
  - Scope the feedback source before clustering.
  - Separate bug signals, feature asks, severity, opportunity, and evidence gaps.
  - Recommend research, strategy, planning, or coding only as a next workflow, not as observed execution.
- Inputs:
  - feedback items or summary
  - source boundary
  - product area
- Outputs:
  - clusters
  - severity or opportunity ranking
  - next workflow recommendation
- Stop conditions:
  - source boundary is explicit
  - clusters are labeled
  - next workflow is conservative
- Verification:
  - separate bug signals from feature asks
  - rank severity and opportunity
  - avoid default coding handoff
- Evidence ladder:
  - `feedback_source_scoped`
  - `clusters_recorded`
  - `severity_opportunity_recorded`
  - `next_workflow_recommended`
- Wrapper actions:
  - `show_triage`
  - `ask_followup`
  - `prepare_plan`
  - `show_status`
- Artifact events:
  - `feedback_source_scoped`
  - `feedback_cluster_recorded`
  - `next_workflow_recorded`
- Delegation expectation: Record feedback triage as Hermes-retained analysis; record coding handoff only after explicit accepted coding intent.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Feedback triage is not a roadmap, implementation plan, or coding handoff by default.
  - A bug signal is not proof that a fix was implemented or verified.
- Fallback: If feedback items are too vague, ask for source or sample items before ranking severity.

### ops-review

Summarize observed operating status, risks, blockers, priorities, and follow-up actions.

- Use when: Use when recurring work needs a weekly/status/operating review with evidence boundaries.
- Quality tier: `status-gated`
- Quality bar:
  - Tie status claims to observed evidence or mark them as unknown.
  - Separate risks, blockers, priorities, and follow-up actions.
  - Do not infer review, CI, release, or merge readiness from an ops summary alone.
- Inputs:
  - status evidence
  - scope
  - time window
  - known risks
- Outputs:
  - status summary
  - risks
  - blockers
  - priorities
  - follow-up actions
- Stop conditions:
  - status claims are evidence-bound
  - risks and blockers are separated
  - follow-ups are explicit
- Verification:
  - check evidence gaps
  - separate facts from risks
  - record follow-up ownership when known
- Evidence ladder:
  - `review_scope_recorded`
  - `status_evidence_recorded`
  - `risks_blockers_recorded`
  - `priorities_recorded`
  - `followups_recorded`
- Wrapper actions:
  - `show_status`
  - `record_blocker`
  - `record_checkpoint`
  - `prepare_plan`
- Artifact events:
  - `ops_scope_recorded`
  - `status_recorded`
  - `followups_recorded`
- Delegation expectation: Record ops review as Hermes-retained status work; execution evidence requires later observed task records.
- Privacy default: `metadata_only`
- Overclaim guards:
  - An ops review is not release, CI, review, merge, or implementation evidence.
  - Missing evidence must stay unknown, not inferred green.
- Fallback: If evidence is missing, produce a review scaffold and mark unknowns instead of claiming status.

### operating-rhythm

Maintain meeting, scrum, sprint, retro, decision, and follow-up history with prepared-vs-observed boundaries.

- Use when: Use when recurring operating cadence records need durable structure or history.
- Quality tier: `operations-gated`
- Quality bar:
  - Name cadence, audience, time window, known notes, and missing evidence before producing a record.
  - Separate templates from observed minutes, decisions, and action items.
  - Keep follow-up implementation outside the operating record until a separate handoff is accepted.
- Inputs:
  - cadence or meeting type
  - audience or participants
  - time window
  - source notes or missing-notes boundary
- Outputs:
  - operation artifact
  - decision log
  - action item history
  - observed/prepared boundary
- Stop conditions:
  - record structure is ready
  - observed notes are separated from prepared shells
  - unknown owners or decisions stay explicit
- Verification:
  - validate operation_artifact/v1
  - check not_evidence_until_observed
  - separate decisions from action items
- Evidence ladder:
  - `operation_rhythm_scoped`
  - `record_structure_prepared`
  - `decisions_actions_recorded`
  - `status_boundary_recorded`
- Wrapper actions:
  - `show_record`
  - `record_decision`
  - `record_action`
  - `export_markdown`
  - `show_status`
- Artifact events:
  - `operation_rhythm_scoped`
  - `record_structure_prepared`
  - `decisions_actions_recorded`
  - `status_boundary_recorded`
- Delegation expectation: Record operating rhythm as Hermes-retained operations work; record implementation only from later accepted task records.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared operating record is not evidence that a meeting, scrum, sprint, or retro happened.
  - Draft decisions and action items are not accepted outcomes without supplied evidence.
- Fallback: If notes are missing, create a prepared record shell and mark meeting outcomes not_observed.

### report-package

Package supplied inputs into reports, executive briefs, and PPT-ready Markdown/JSON outlines.

- Use when: Use when report, deck, or upload-package work needs structured outputs without reliability coupling.
- Quality tier: `report-gated`
- Quality bar:
  - Name audience, period, sections, supplied facts, assumptions, and missing data.
  - Keep report packaging independent from SLO, incident, or error-budget review unless explicitly requested.
  - Export only Markdown/JSON outline artifacts unless a presentation generator observes binary deck creation.
- Inputs:
  - audience
  - reporting period or scope
  - supplied facts
  - assumptions or missing data
- Outputs:
  - report package
  - PPT-ready Markdown or JSON outline
  - assumptions and missing-input list
- Stop conditions:
  - audience and sections are explicit
  - facts and assumptions are separated
  - export scope is bounded
- Verification:
  - validate operation_artifact/v1
  - check assumptions
  - export Markdown/JSON only unless another tool makes a deck
- Evidence ladder:
  - `report_scope_recorded`
  - `inputs_organized`
  - `package_outline_prepared`
  - `approval_boundary_recorded`
- Wrapper actions:
  - `show_report`
  - `export_markdown`
  - `export_json`
  - `record_approval`
  - `show_status`
- Artifact events:
  - `report_scope_recorded`
  - `inputs_organized`
  - `package_outline_prepared`
  - `approval_boundary_recorded`
- Delegation expectation: Record report packaging as Hermes-retained operations work; record stakeholder approval or presentation delivery only when observed.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A report package is not source-review completion, stakeholder approval, or presentation delivery evidence.
  - A PPT-ready outline is not a binary PPTX export.
  - Report packaging does not require reliability evidence unless the user asks for reliability review.
- Fallback: If inputs are missing, produce a report scaffold and missing-data list instead of fabricating numbers.

### materials-package

Plan, hand off, and verify material-processing work across decks, PDFs, spreadsheets, documents, HWP, Markdown, and binary exports.

- Use when: Use when a Hermes request needs target-format selection, source-input packaging, document-generation handoff, export tracking, or render/formula QA.
- Quality tier: `material-gated`
- Quality bar:
  - Name audience, source inputs, target formats, outline sections, missing inputs, assumptions, and output owner.
  - Represent Markdown/JSON outline, binary export, render QA, spreadsheet formula checks, approval, and delivery as separate stages.
  - Keep PPTX, PDF, Keynote, DOCX, XLSX, HWP, upload, and delivery claims unavailable until observed file or wrapper evidence exists.
- Inputs:
  - audience or recipient
  - source inputs
  - target format(s)
  - outline sections
  - missing inputs or assumptions
- Outputs:
  - material_artifact/v1 plan
  - format-specific QA ladder
  - generation handoff when needed
  - observed export boundary
- Stop conditions:
  - target formats are explicit
  - missing inputs are recorded
  - binary export and QA stay observed-only
- Verification:
  - validate material_artifact/v1
  - check target format QA ladder
  - record binary export only from observed files
  - record approval or delivery only from observed evidence
- Evidence ladder:
  - `material_scope_recorded`
  - `source_inputs_organized`
  - `format_qa_ladder_prepared`
  - `generation_handoff_prepared_if_needed`
  - `export_qa_observed_when_available`
- Wrapper actions:
  - `show_material_plan`
  - `choose_target_format`
  - `prepare_generation_handoff`
  - `record_export`
  - `record_qa`
  - `record_approval`
  - `show_status`
- Artifact events:
  - `material_scope_recorded`
  - `source_inputs_organized`
  - `format_qa_ladder_prepared`
  - `generation_handoff_prepared_if_needed`
  - `export_qa_observed_when_available`
- Delegation expectation: Record material packaging as Hermes-retained planning work; record file generation, QA, approval, upload, or delivery only when a wrapper/operator observes evidence.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A material_artifact/v1 plan is not binary PPTX, PDF, Keynote, DOCX, XLSX, HWP, or upload evidence.
  - Planned QA checks are not render QA, formula recalculation, approval, or delivery evidence.
- Fallback: If source data or target format is missing, create a material scaffold and ask for the smallest missing input before generation.

### img-summary

Prepare source-specific, premium domain-aware, and poster-archetype-aware visual prompt cards for meetings, reports, PRs, issue feedback, research briefings, and release announcements without claiming image generation.

- Use when: Use when Hermes should turn supplied source or structured card fields into a provider-neutral image-generation prompt card with an appropriate format profile, domain theme, poster archetype, premium background plate/texture/camera direction, and stable OMH generated mark.
- Quality tier: `visual-card-gated`
- Quality bar:
  - Use meeting, PR, issue, research, report, and release format profiles instead of one fixed grid.
  - Use domain-aware premium background plates, real-feeling textures, camera treatment, lighting, and motifs so security looks like a security system, sports looks athletic, fashion looks editorial, and commerce looks retail/product-led.
  - Use poster archetypes as distinct visual grammar, not color presets: sports_event should feel like an event poster, luxury_lookbook like a lookbook, technical_brutalist like a systems poster, and data_infographic like an analysis poster.
  - Reject color-only restyling; require a rich photographed, cinematic, or high-end 3D environment under the readable modules rather than flat template variants.
  - Keep the OMH generated mark, evidence footer, and source badge stable even when the visual style changes.
  - Keep visual card copy source-faithful and readable at the selected aspect ratio; extend the canvas when content needs more room.
  - Represent structured sections and extractive drafts separately.
  - Never treat connected image capability as generated image evidence.
  - Keep generated image, visual QA, and delivery as separate observed records.
- Inputs:
  - source kind
  - visual format
  - poster archetype
  - aspect ratio
  - audience
  - language mode
  - headline or source text
  - structured sections or extractive source excerpts
- Outputs:
  - visual_prompt_card/v1
  - source-specific visual format
  - detected domain_key
  - domain-aware visual theme
  - poster_archetype/v1
  - poster archetype visual grammar
  - premium background plate/scene/texture/camera/lighting direction
  - image-safe card copy
  - generation prompt
  - negative prompt
  - quality checks
  - available wrapper actions
- Stop conditions:
  - prompt card is prepared
  - copy mode is explicit
  - format profile is source-specific
  - visual theme is domain-aware
  - poster archetype is explicit
  - image generation, visual QA, and delivery remain observed-only
- Verification:
  - validate visual_prompt_card/v1
  - check source kind and language mode
  - check visual format and aspect ratio
  - check top-level visual_theme and style_direction domain_key mirrors
  - check visual_theme and OMH generated format contract
  - check poster_archetype/v1 and source/domain/archetype separation
  - check scene_quality/background_plate/material_texture/depth_lighting/camera_treatment guidance
  - ensure raw source uses extractive_draft copy mode
  - record visual_observation/v1 only for supplied generated image, QA, or delivery evidence
- Evidence ladder:
  - `source_kind_selected`
  - `visual_format_selected`
  - `poster_archetype_selected`
  - `card_copy_prepared`
  - `prompt_card_prepared`
  - `image_generation_capability_checked`
  - `generated_image_observed_when_available`
  - `visual_qa_observed_when_available`
  - `delivery_observed_when_available`
- Wrapper actions:
  - `show_visual_prompt_card`
  - `copy_visual_prompt`
  - `revise_visual_card`
  - `change_visual_language`
  - `choose_image_generator`
  - `setup_image_generator`
  - `generate_visual_image`
  - `record_visual_image`
  - `record_visual_qa`
  - `record_visual_delivery`
  - `show_visual_status`
- Artifact events:
  - `visual_card_prepared`
  - `generation_action_available_when_connected`
  - `visual_observation_recorded_when_available`
- Delegation expectation: Record img-summary as Hermes-retained prompt-card preparation; record image generation, visual QA, and delivery only from visual_observation/v1 evidence.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A visual_prompt_card/v1 artifact is not generated image, visual QA, sharing, posting, attachment, or delivery evidence.
  - An image_generation_setup/v1 fallback is connector preparation only, not generated image evidence.
  - A connected image-generation capability changes available actions only; it is not execution evidence.
  - A generated image observation does not prove visual QA or delivery.
- Fallback: If image capability is unavailable, show choose/setup image tool fallback actions plus copy/revise/status actions, and keep generation prompt-only until capability is connected.

### scheduled-ops-blueprint

Prepare recurring Hermes operations as schedule/delivery/silence blueprints without claiming runtime execution.

- Use when: Use when recurring, cron-like, digest, monitoring, or platform-delivery requests need a Hermes-native setup plan and status card.
- Quality tier: `ops-blueprint-gated`
- Quality bar:
  - Name cadence, timezone uncertainty, delivery target, silence policy, selected skills, context chain, and missing decisions.
  - Separate prepared host schedule guidance from observed Hermes automation or cron evidence.
  - Separate delivery intent from gateway/platform delivery proof.
  - Expose no-agent suitability only as a candidate classification unless no-agent runtime evidence is observed.
- Inputs:
  - recurring request
  - cadence or schedule hint
  - delivery target
  - silence/no-change policy
- Outputs:
  - hermes_ops_blueprint/v1
  - schedule/delivery/silence policy
  - skill context chain
  - not-evidence boundary
- Stop conditions:
  - blueprint is prepared
  - missing schedule/delivery decisions are explicit
  - runtime and delivery claims remain observed-only
- Verification:
  - validate hermes_ops_blueprint/v1
  - check schedule/delivery/silence fields
  - verify not_evidence_until_observed lists runtime and gateway claims
- Evidence ladder:
  - `blueprint_scope_recorded`
  - `schedule_policy_prepared`
  - `delivery_policy_prepared`
  - `silence_policy_prepared`
  - `context_chain_prepared`
  - `runtime_observed_when_available`
- Wrapper actions:
  - `show_blueprint`
  - `revise_schedule`
  - `confirm_delivery_policy`
  - `prepare_host_schedule`
  - `record_observed_runtime`
  - `show_status`
- Artifact events:
  - `blueprint_scope_recorded`
  - `schedule_policy_prepared`
  - `delivery_policy_prepared`
  - `status_boundary_recorded`
- Delegation expectation: Record scheduled ops blueprints as Hermes-retained projection metadata; record host automation, delivery, retrieval, or no-agent execution only from observed runtime evidence.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A hermes_ops_blueprint/v1 artifact is not host cron creation, Hermes automation, gateway delivery, source retrieval, no-agent execution, plugin load, or connector evidence.
  - A silence policy is not proof that a run happened or that there were no changes.
  - No-agent suitability is only a design hint until a no-agent runtime record exists.
- Fallback: If cadence, delivery, or silence policy is missing, prepare the blueprint and ask for the smallest missing confirmation.

### research-department

Prepare Scout, Analyst, and Briefer research operations with source inbox and briefing status boundaries.

- Use when: Use when recurring or durable market, competitor, paper, news, or source-monitoring research should become a Hermes workflow pack.
- Quality tier: `research-ops-gated`
- Quality bar:
  - Name topic, source boundaries, cadence, delivery target, knowledge-store destination, and synthesis-tool readiness.
  - Map Scout, Analyst, and Briefer lanes to concrete OMH skills and source inbox buckets.
  - Expose collected, synthesized, briefed, conflict, and verification counts as status, not execution proof.
  - List required evidence before claiming retrieval, synthesis-tool, knowledge-store, delivery, or verification.
- Inputs:
  - topic or watch area
  - source boundaries
  - cadence
  - delivery target
  - knowledge-store preference
  - synthesis-tool preference
- Outputs:
  - research_department_plan/v1
  - source_inbox/v1
  - briefing_status/v1
  - not-evidence boundary
- Stop conditions:
  - research lanes are prepared
  - source inbox buckets are separated
  - retrieval, synthesis, storage, delivery, and verification claims remain observed-only
- Verification:
  - validate research_department_plan/v1
  - check Scout/Analyst/Briefer lane mapping
  - verify not_evidence_until_observed lists retrieval, synthesis-tool, knowledge-store, scheduler, and delivery claims
- Evidence ladder:
  - `research_plan_scope_recorded`
  - `source_inbox_prepared`
  - `briefing_status_prepared`
  - `tooling_readiness_prepared`
  - `observed_evidence_recorded_when_available`
- Wrapper actions:
  - `show_research_department_plan`
  - `revise_research_sources`
  - `confirm_cadence_delivery_tooling`
  - `record_source_observation`
  - `show_status`
- Artifact events:
  - `research_plan_scope_recorded`
  - `source_inbox_prepared`
  - `briefing_status_prepared`
  - `tooling_readiness_prepared`
- Delegation expectation: Record research department plans as Hermes-retained projection metadata; record source retrieval, synthesis-tool output, knowledge-store writes, delivery, and verification only from observed evidence.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A research_department_plan/v1 artifact is not source retrieval, synthesis-tool execution, knowledge-store writes, host cron creation, gateway delivery, or verification evidence.
  - Source inbox buckets are not proof that source content was fetched or processed.
  - Briefing status counts are only prepared status until matching source, synthesis, storage, delivery, or review evidence exists.
- Fallback: If topic, sources, cadence, delivery, knowledge-store, or synthesis-tool preferences are missing, prepare the plan and ask for the smallest missing confirmation.

### reliability-review

Review incidents, SLOs, error budgets, and remediation follow-ups with strict observed evidence boundaries.

- Use when: Use when SRE-style incident, postmortem, SLO, error-budget, or service reliability review is requested.
- Quality tier: `reliability-gated`
- Quality bar:
  - Name service, incident/time window, SLO/error-budget target, source references, and missing observations.
  - Separate supplied metrics, incident notes, assumptions, and remediation follow-ups.
  - Keep SLO pass, error-budget health, incident closure, and remediation completion unobserved until evidence is supplied.
- Inputs:
  - service or incident scope
  - time window
  - metric/source references
  - known remediation items or gaps
- Outputs:
  - reliability review
  - evidence and missing-evidence list
  - remediation follow-up boundary
- Stop conditions:
  - source or metric boundary is explicit
  - missing evidence is recorded
  - closure claims remain observed-only
- Verification:
  - validate operation_artifact/v1
  - require source/metric/reference for observed claims
  - check remediation status separately
- Evidence ladder:
  - `reliability_scope_recorded`
  - `evidence_boundary_recorded`
  - `review_prepared_or_observed`
  - `remediation_boundary_recorded`
- Wrapper actions:
  - `show_evidence`
  - `record_gap`
  - `prepare_handoff`
  - `record_metric`
  - `show_status`
- Artifact events:
  - `reliability_scope_recorded`
  - `evidence_boundary_recorded`
  - `review_prepared_or_observed`
  - `remediation_boundary_recorded`
- Delegation expectation: Record reliability review as Hermes-retained evidence work; record remediation implementation only from later accepted executor evidence.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A reliability review is not SLO pass, healthy error-budget, incident closure, or remediation completion evidence.
  - Remediation code changes require a separate accepted executor handoff and verification evidence.
- Fallback: If metric or incident evidence is unavailable, produce a prepared review scaffold and mark closure evidence not_observed.

### app-delivery-loop

Run complete app operation loops from idea through decision, handoff, release, deploy, and monitor status.

- Use when: Use when a Hermes wrapper needs a finished-product-feeling path for idea-to-deploy, CTO loops, or deploy-and-monitor work without hidden coding or infrastructure execution.
- Quality tier: `delivery-gated`
- Quality bar:
  - Name the product or release objective, user/customer value, success metric, non-goals, and owner.
  - Represent idea, decision, plan, handoff, verification, release, deploy, and monitor as separate stages.
  - Keep coding work executor/runtime-neutral until a selected executor, runtime, or Hermes coding owner is chosen and a handoff is accepted.
  - Keep deploy, monitoring, rollback, incident, review, CI, and merge claims unavailable until observed evidence exists.
- Inputs:
  - idea or release request
  - success metric
  - scope constraints
  - evidence sources
- Outputs:
  - stage rail
  - decision gates
  - handoff or retained-work plan
  - deploy/monitor status boundary
- Stop conditions:
  - next stage is accepted or blocked
  - unobserved deploy/monitor claims stay explicit
  - coding work has selected executor/runtime guidance when needed
- Verification:
  - check every stage has an owner
  - separate prepared from observed
  - record deploy and monitor only from evidence
- Evidence ladder:
  - `loop_scope_recorded`
  - `decision_gate_recorded`
  - `plan_or_release_gate_accepted`
  - `handoff_prepared_if_needed`
  - `verification_release_gate_recorded`
  - `deploy_monitor_observed_when_available`
- Wrapper actions:
  - `show_delivery_loop`
  - `accept_plan`
  - `choose_executor`
  - `prepare_handoff`
  - `record_deploy`
  - `record_monitor_signal`
  - `show_status`
- Artifact events:
  - `delivery_loop_scoped`
  - `decision_gate_recorded`
  - `handoff_or_release_status_recorded`
- Delegation expectation: Record app delivery loop evidence only when Hermes, a wrapper, or an operator observes stage acceptance, handoff, deploy, or monitoring events.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared app delivery loop is not implementation, deploy, monitor, rollback, incident, review, CI, merge-readiness, or merge evidence.
  - A CTO loop recommendation is not an accepted decision unless decision evidence is recorded.
  - A health watchlist is not observed health evidence.
- Fallback: If release scope, owner, or evidence is missing, show the loop scaffold and ask for the smallest missing decision before advancing.

### goal-loop

Run loopable goal projects through task/project/ambition classification, bounded goal shaping, task discovery, distribution, execution, verification tiers, verifier checks, next-task decisions, runtime ticks with deterministic queue shapes, handoff, feedback, waiting, and resumable status without hidden execution.

- Use when: Use when a direct loop invocation or explicit long-horizon goal needs to decide whether it is too small, too large, or truly loopable before repeated cycles over automation, worktree, skill, connector, subagent, and verification building blocks.
- Quality tier: `loop-gated`
- Quality bar:
  - Confirm the direct loop trigger and classify whether the goal is a task, project, ambition, external-wait outcome, or unclear request before cycling.
  - Route direct tasks away from loop overhead and convert ambitions into a north star plus one bounded current loop goal.
  - Confirm north-star goal, bounded arena, observable problem, next verification, reframe, success criteria, and permission profile before cycling.
  - Separate implementable internal work from external outcomes such as stars, market reaction, adoption, or social distribution.
  - Continue automatically only inside the selected authority envelope; otherwise surface a permission action.
  - Use runtime ticks with deterministic queue shapes to prepare automation, worktree, skill, connector, subagent, and verification states, but require separate observed evidence before claiming those steps ran.
  - Keep loop_engineering/v1 focused on bounded state and evidence refs rather than dumping large intermediate context into the parent loop.
  - Use fan-out, adversarial verification, tournament, or triage-batch workflow patterns for research validation, support triage, or implementation review only when the extra lanes add evidence value.
  - Keep the schema scaffold stable for repeated ticks and avoid re-scanning or re-emitting large context when evidence refs are enough.
  - Use inner-loop checks for frequent cheap confidence and outer-loop checks for expensive semantic or integration confidence.
  - Surface verification_gap, comprehension_debt, and cognitive_surrender before the loop continues without enough judgment.
  - Keep small-loop guidance visible: test as stop signal, plan -> execute -> verify, one task at a time.
  - Treat feedback as a gate: clear internal actionable gaps continue the loop; external waiting records a wait state.
  - Never report goal completion from loop state unless linked goal_ledger/v1 completion evidence is ready.
- Inputs:
  - loopability assessment
  - north-star goal summary when present
  - bounded arena
  - observable problem
  - next verification
  - reframed implementable target
  - success criteria
  - permission profile
  - feedback or wait signal
- Outputs:
  - loopability_assessment/v1
  - loop_start_card/v1 setup card
  - loop_cycle/v1 artifact
  - loop_engineering/v1 pipeline/building-block snapshot
  - loop verification_policy for inner and outer checks
  - loop_runtime/v1 queue entry with verification_plan
  - loop_queue_handoff/v1 actionable handoff
  - loop_subagent_result_contract/v1 when a subagent is planned
  - loop_status_card/v1 next action with failure_mode_summary
  - small_loop_guidance
  - permission envelope
  - linked goal or runtime evidence references when available
- Stop conditions:
  - goal is classified as task/project/ambition/external-wait/unclear
  - next loop step is clear
  - runtime tick queue is prepared, observed, or blocked with a reason
  - automation/worktree/skill/connector/subagent block states are visible
  - verification tier and stop signal are explicit
  - failure-mode warnings are visible
  - permission boundaries are explicit
  - external waiting and context exhaustion are recorded
  - goal completion claims are delegated to goal_ledger/v1
- Verification:
  - validate loopability_assessment/v1
  - validate loop_cycle/v1
  - inspect loop_engineering/v1 snapshot
  - inspect loop_runtime/v1 queue verification_plan
  - inspect loop_status_card/v1 failure_mode_summary
  - inspect loop_queue_handoff/v1 when a queued item is actionable
  - check linked goal_completion_gate/v1 before completion copy
- Evidence ladder:
  - `loop_triggered`
  - `loopability_assessed`
  - `goal_reframed`
  - `permission_profile_recorded`
  - `runtime_tick_queued`
  - `verification_plan_attached`
  - `research_plan_handoff_cycle_recorded`
  - `feedback_gate_evaluated`
  - `failure_modes_checked`
  - `wait_or_resume_boundary_recorded`
- Wrapper actions:
  - `assess_loopability`
  - `convert_to_loop_goal`
  - `route_direct_task`
  - `choose_permission_profile`
  - `start_loop`
  - `run_loop_once`
  - `run_loop_tick`
  - `show_loop_queue`
  - `prepare_loop_handoff`
  - `observe_loop_queue`
  - `block_loop_queue`
  - `show_loop_status`
  - `prepare_handoff`
  - `choose_executor`
  - `show_status`
- Artifact events:
  - `loop_started`
  - `permission_profile_recorded`
  - `feedback_gate_recorded`
  - `loop_status_card_rendered`
- Delegation expectation: Record loop state as Hermes-retained orchestration; record executor/runtime dispatch, implementation, review, CI, merge, and external publication only when observed by a linked runtime or operator artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A loop_cycle/v1 artifact is not proof that coding, review, CI, merge, or external publication happened.
  - A loop_runtime/v1 tick is not proof that a worktree, subagent, connector, or executor actually ran.
  - A loop verification_plan is not proof that verification passed.
  - A full-loop permission profile is still bounded by observed evidence and explicit external-production authority.
  - External outcomes stay waiting_external_observation until evidence is recorded.
- Fallback: If no wrapper or CLI artifact is available, keep a visible checklist with the same permission profile and evidence boundaries.

### deep-interview

Clarify intent and boundaries one question at a time before planning or execution.

- Use when: Use when intent, scope, non-goals, or decision authority are unclear.
- Quality tier: `clarity-gated`
- Quality bar:
  - Name the missing decision, why it matters, and the smallest answer that would unblock the next step.
  - Ask one blocking question tied to a missing decision.
  - Use discovered facts before asking the user for information already available locally.
  - Produce a clarified brief with non-goals, acceptance criteria, and remaining unknowns before planning or handoff.
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
  - `blocking_question_asked`
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
  - Documentation of a future surface is not proof that evidence was observed.
  - Generated docs must match catalog data before release claims are made.
- Fallback: If behavior is not implemented yet, label it as roadmap instead of current capability.

### github-event-ops

Route GitHub PR, issue, CI, and review events into triage, review, labeling, or fix-handoff guidance.

- Use when: Use when a GitHub event payload or copied event summary should become a Hermes workflow card.
- Quality tier: `event-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - event type
  - repository or project
  - event summary
  - desired automation boundary
- Outputs:
  - github_event_ops/v1
  - route decision
  - label/review/fix-handoff candidates
  - not-evidence list
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `event_received`
  - `event_classified`
  - `route_card_prepared`
  - `mutation_observed_when_available`
- Wrapper actions:
  - `show_event_card`
  - `prepare_review`
  - `prepare_label`
  - `prepare_fix_handoff`
  - `record_github_observation`
- Artifact events:
  - `github-event-ops_scoped`
  - `github-event-ops_card_prepared`
  - `github-event-ops_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A GitHub event card is not webhook delivery, API mutation, label application, review completion, CI rerun, or fix execution evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### agent-board

Coordinate multi-Hermes-agent or profile work as board cards with task, handoff, heartbeat, blocker, and completion states.

- Use when: Use when target topology or team profile work needs board-style status rather than plain chat summaries.
- Quality tier: `board-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - board scope
  - known agents or profiles
  - task cards
  - current target/thread
- Outputs:
  - agent_board/v1
  - card states
  - target-scoped status
  - blocked or complete evidence boundary
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `board_scoped`
  - `cards_prepared`
  - `heartbeat_recorded_when_available`
  - `completion_recorded_when_available`
- Wrapper actions:
  - `show_board`
  - `move_card`
  - `record_heartbeat`
  - `record_blocker`
  - `record_completion`
- Artifact events:
  - `agent-board_scoped`
  - `agent-board_card_prepared`
  - `agent-board_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A board state is not proof that another Hermes target accepted, worked, heartbeat-ed, or completed unless target-specific evidence exists.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### memory-curation-review

Review stale, conflicting, duplicate, or risky memory and skill guidance with explicit approve/reject/update actions.

- Use when: Use when accumulated memory, USER/MEMORY files, or skill notes need human-approved cleanup.
- Quality tier: `curation-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - memory source summary
  - candidate memories or skills
  - staleness/conflict signal
  - review owner
- Outputs:
  - memory_curation_review/v1
  - approve/reject/update candidates
  - conflicts
  - write boundary
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `memory_candidates_scoped`
  - `conflicts_ranked`
  - `review_actions_prepared`
  - `approved_write_observed_when_available`
- Wrapper actions:
  - `show_memory_review`
  - `approve_update`
  - `reject_update`
  - `record_memory_write`
  - `show_status`
- Artifact events:
  - `memory-curation-review_scoped`
  - `memory-curation-review_card_prepared`
  - `memory-curation-review_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A memory review is not Hermes internal memory, MEMORY.md, USER.md, or skill-file modification evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### gateway-intent-card

Normalize gateway session policy for origin, thread, delivery, silent updates, attachments, and status updates.

- Use when: Use when Discord, Slack, Telegram, or another gateway wrapper needs platform-neutral intent before delivery.
- Quality tier: `gateway-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - origin platform
  - thread/session id or boundary
  - delivery target
  - silence and attachment policy
- Outputs:
  - gateway_intent_card/v1
  - delivery policy
  - status-update policy
  - not-evidence list
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `origin_scoped`
  - `thread_policy_prepared`
  - `delivery_policy_prepared`
  - `delivery_observed_when_available`
- Wrapper actions:
  - `show_gateway_card`
  - `confirm_delivery`
  - `record_delivery`
  - `record_attachment`
  - `show_status`
- Artifact events:
  - `gateway-intent-card_scoped`
  - `gateway-intent-card_card_prepared`
  - `gateway-intent-card_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A gateway intent card is not login, platform send, thread mutation, attachment upload, or delivery evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### executor-runtime-readiness

Compare executor/runtime options by available tools, missing tools, credentials, authority, and handoff mode.

- Use when: Use before choosing Codex, Claude Code, Hermes coding, or an oh-my runtime for coding or tool-backed work.
- Quality tier: `runtime-readiness-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - task shape
  - candidate runtime
  - available tools
  - missing credentials or authority
- Outputs:
  - executor_runtime_readiness/v1
  - runtime matrix
  - handoff mode
  - missing tool list
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `task_runtime_scoped`
  - `tool_matrix_prepared`
  - `handoff_mode_selected`
  - `runtime_dispatch_observed_when_available`
- Wrapper actions:
  - `show_runtime_matrix`
  - `choose_executor`
  - `prepare_handoff`
  - `record_dispatch`
  - `show_status`
- Artifact events:
  - `executor-runtime-readiness_scoped`
  - `executor-runtime-readiness_card_prepared`
  - `executor-runtime-readiness_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Runtime readiness is not executor dispatch, plugin load, tool invocation, code execution, review, CI, or merge evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### deliverable-package

Track file deliverables through prepared, generated, QA, approved, attached, and delivered states.

- Use when: Use when Hermes should prepare or status a PPT/PDF/XLSX/DOCX/HWP/Markdown deliverable in chat.
- Quality tier: `deliverable-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - source inputs
  - target formats
  - audience
  - delivery or attachment target
- Outputs:
  - deliverable_package/v1
  - format plan
  - QA ladder
  - attachment/delivery state
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `deliverable_scoped`
  - `format_plan_prepared`
  - `generation_handoff_prepared`
  - `file_observed_when_available`
  - `attachment_observed_when_available`
- Wrapper actions:
  - `show_deliverable_card`
  - `choose_format`
  - `prepare_generation_handoff`
  - `record_file`
  - `record_attachment`
- Artifact events:
  - `deliverable-package_scoped`
  - `deliverable-package_card_prepared`
  - `deliverable-package_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A deliverable package card is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### voice-operator

Convert terse voice/mobile requests into safe clarify, plan, status, handoff, or confirmation actions.

- Use when: Use when the input is short, ambiguous, mobile, voice-like, or accessibility-sensitive.
- Quality tier: `accessibility-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - voice/mobile transcript
  - confidence or ambiguity
  - current thread context
  - risk level
- Outputs:
  - voice_operator/v1
  - clarification or action card
  - confirmation requirement
  - status copy
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `voice_request_received`
  - `ambiguity_checked`
  - `safe_action_prepared`
  - `confirmation_observed_when_required`
- Wrapper actions:
  - `ask_clarification`
  - `confirm_action`
  - `show_status`
  - `prepare_handoff`
- Artifact events:
  - `voice-operator_scoped`
  - `voice-operator_card_prepared`
  - `voice-operator_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A voice operator card is not speech recognition proof, mobile notification delivery, platform action, or accepted execution evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### toolbelt-readiness

Check required MCP servers, CLIs, APIs, credentials, connectors, and local tools for a workflow.

- Use when: Use when a workflow may require external tools and the user needs installed, missing, optional, and unsafe tool state.
- Quality tier: `tool-readiness-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - workflow goal
  - required tools
  - known environment
  - credential policy
- Outputs:
  - toolbelt_readiness/v1
  - tool matrix
  - missing credentials
  - safe next action
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `workflow_tools_scoped`
  - `tool_requirements_listed`
  - `installed_state_recorded_when_available`
  - `credential_gaps_recorded`
- Wrapper actions:
  - `show_toolbelt`
  - `open_setup`
  - `record_tool_check`
  - `prepare_handoff`
  - `show_status`
- Artifact events:
  - `toolbelt-readiness_scoped`
  - `toolbelt-readiness_card_prepared`
  - `toolbelt-readiness_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A toolbelt readiness card is not MCP installation, credential validation, API access, connector invocation, or successful workflow execution evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### ops-observability-card

Report wrapper-safe token, cost, latency, run history, queue, and failure-mode telemetry boundaries.

- Use when: Use when automation, loops, gateway work, or executor sessions need safe observability and cost/status narration.
- Quality tier: `observability-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - workflow/run id
  - available telemetry
  - cost/token policy
  - history window
- Outputs:
  - ops_observability_card/v1
  - telemetry summary
  - cost/latency boundary
  - failure-mode warnings
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `telemetry_scope_recorded`
  - `local_metrics_summarized`
  - `failure_modes_checked`
  - `provider_truth_observed_when_available`
- Wrapper actions:
  - `show_observability`
  - `record_metric`
  - `record_failure_mode`
  - `show_status`
- Artifact events:
  - `ops-observability-card_scoped`
  - `ops-observability-card_card_prepared`
  - `ops-observability-card_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - An ops observability card is not billing truth, provider quota truth, complete tracing, performance proof, or workflow completion evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.

### agent-ops-review

Prepare a manager-facing quality and throughput review for AI-agent research, coding, review, and status work.

- Use when: Use when a third-party operator or team lead wants to understand progress, blockers, quality gates, next actions, and safe throughput levers without running shell catalog commands.
- Quality tier: `manager-review-gated`
- Quality bar:
  - Name the workflow objective, owner, input boundary, next action, and stop condition.
  - Represent prepared, observed, blocked, and missing evidence as separate states.
  - Never upgrade a card, blueprint, or readiness check into external execution proof.
- Inputs:
  - manager request
  - work context or run/session references when available
  - target outcome
  - known evidence gaps
- Outputs:
  - agent_operator_productivity/v1
  - agent_operator_status_card/v1
  - quality lanes
  - blockers
  - next action
  - throughput levers
- Stop conditions:
  - card is prepared or a missing decision is surfaced
  - observed evidence is separated from prepared guidance
- Verification:
  - validate required fields
  - check not-evidence boundaries
  - record only observed external actions
- Evidence ladder:
  - `manager_scope_recorded`
  - `quality_lanes_prepared`
  - `evidence_gaps_named`
  - `next_action_selected`
  - `runtime_observation_recorded_when_available`
- Wrapper actions:
  - `show_agent_ops_review`
  - `choose_ops_lane`
  - `prepare_research_lane`
  - `prepare_coding_lane`
  - `prepare_review_lane`
  - `refresh_agent_ops_status`
  - `record_agent_ops_observation`
- Artifact events:
  - `agent-ops-review_scoped`
  - `agent-ops-review_card_prepared`
  - `agent-ops-review_status_recorded`
- Delegation expectation: Record this harness as Hermes-retained orchestration; external runtime/platform/file/memory/connector evidence requires a separate observed artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - An agent ops review card is not source retrieval, executor dispatch, implementation, verification, review, CI, merge, delivery, provider billing, or live telemetry evidence.
- Fallback: If a required target, credential, runtime, or observation is missing, show a blocker or confirmation action instead of claiming completion.
