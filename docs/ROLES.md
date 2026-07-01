# OMH Role Surface

OMH roles are responsibility descriptors, not runtime agents. They make chat responses, wrapper buttons, and status cards easier to read without claiming that a separate worker exists or ran.

Use roles inside the flagship `request-to-handoff` path:

`plain request -> responsible role -> plan/status/handoff action -> observed evidence boundary`

## OMH Role Context

Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible.

Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user learn backend OMH commands.

Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, review, CI, merge-readiness, or merge evidence.

## Operating Models

Operating models are lighter than role profile packs. They can record an
advanced default Hermes collaboration posture for a specific profile, but normal
setup does not force users to choose one and they do not install role files or
claim that separate agents ran.

| ID | Default posture |
| --- | --- |
| `solo-operator` | Keep the safest single-operator defaults and ask before executor dispatch. |
| `small-team` | Bias chat narration toward product, technical, QA, and release ownership without installing team files. |
| `research-ops` | Keep Hermes focused on research, strategy, and meeting workflows. |
| `coding-runtime-team` | Make selected Hermes/OMX/OMO/OMC runtime handoffs and observed runtime ladder status first-class. |

Use `omh setup --operating-model <id>` only when a profile should start from one
of these postures. Use `omh setup --profile-pack <id>` only when you also want
visible role files under Hermes.

An operating model is an organization pattern for Hermes chat, not proof that
any worker or executor ran. The map below shows where roles shape chat routing,
prepared handoffs, and observed evidence:

<p align="center">
  <img src="../assets/omh-profile-interaction-map.svg" alt="OMH request-to-handoff role interaction map" width="920">
</p>

## Roles

### Guide

- ID: `guide`
- Display name: Guide
- Legacy aliases: `hybrid-guidance`, `retained-router`
- Purpose: Own first-touch routing, workflow selection, concise clarification, and the next visible Hermes action.
- Owns:
  - Plain request intake and route explanation
  - Skill or playbook recommendation
  - One focused clarification when routing signals conflict
- Primary skills: `oh-my-hermes`, `voice-operator`, `gateway-intent-card`
- Primary harnesses: `routing`, `chat-wrapper`
- Wrapper actions: `ask_followup`, `show_status`, `route_request`
- Evidence boundary: A guide role can choose or explain a route; it is not plan acceptance, dispatch, execution, review, CI, or merge evidence.

### Researcher

- ID: `researcher`
- Display name: Researcher
- Legacy aliases: `research-lead`
- Purpose: Own source-backed discovery and keep evidence, inference, confidence, freshness, and unknowns separate.
- Owns:
  - Research question and source boundary
  - Observed evidence versus inferred trend
  - Research summary that can feed planning or strategy
- Primary skills: `web-research`, `best-practice-research`, `research-brief`, `autoresearch-goal`
- Primary harnesses: `research`, `business-research`
- Wrapper actions: `ask_followup`, `show_sources`, `show_status`
- Evidence boundary: A researcher role can prepare or summarize evidence; it is not implementation, review, CI, or merge evidence.

### Planner

- ID: `planner`
- Display name: Planner
- Legacy aliases: `planning-lead`
- Purpose: Own clarification, non-goals, acceptance criteria, tradeoffs, loopability, and verification strategy.
- Owns:
  - One-question clarification when scope is ambiguous
  - Plan artifact with goals, non-goals, risks, and verification
  - Decision gate before handoff or execution
- Primary skills: `deep-interview`, `plan`, `ralplan`, `loop`
- Primary harnesses: `deep-interview`, `planning`, `strategy-synthesis`, `goal-loop`
- Wrapper actions: `ask_followup`, `accept_plan`, `revise_plan`, `show_status`
- Evidence boundary: A planner role can make work reviewable; it is not proof that the work was accepted or executed.

### Operator

- ID: `operator`
- Display name: Operator
- Legacy aliases: `retained-operator`
- Purpose: Own non-coding company, product, delivery, meeting, material, and scheduled operations workflows.
- Owns:
  - Business workflow cards and operating records
  - Meeting, strategy, feedback, reliability, report, and material package preparation
  - Delivery or automation state only when observed by a wrapper or host
- Primary skills: `feedback-triage`, `meeting-brief`, `strategy-brief`, `automation-blueprint`, `materials-package`, `report-package`, `reliability-review`, `idea-to-deploy`, `deploy-and-monitor`, `cto-loop`, `operating-rhythm`, `ops-review`, `deliverable-package`, `github-event-ops`
- Primary harnesses: `business-research`, `customer-insight-triage`, `meeting-facilitation`, `materials-package`, `operations`
- Wrapper actions: `show_status`, `prepare_handoff`, `refresh_status`
- Evidence boundary: An operator role can prepare operational workflow guidance; it is not meeting completion, file export, delivery, deploy, monitoring, or external platform evidence.

### Memory Keeper

- ID: `memory-keeper`
- Display name: Memory Keeper
- Legacy aliases: `retained-knowledge`
- Purpose: Own durable context review, project knowledge capture, stale memory warnings, and safe memory update handoffs.
- Owns:
  - Memory and wiki context review
  - Stale, duplicate, or conflicting context candidates
  - Human-approved context pack preparation
- Primary skills: `wiki`, `memory-curation-review`
- Primary harnesses: `knowledge`, `memory-context-review`
- Wrapper actions: `ask_followup`, `show_status`, `prepare_handoff`
- Evidence boundary: A memory keeper role can prepare context changes; it is not proof that Hermes internal memory, USER.md, MEMORY.md, wiki, or skill files were changed.

### Handoff Guide

- ID: `handoff-guide`
- Display name: Handoff Guide
- Legacy aliases: `coding-handoff`, `runtime-handoff-guidance`, `codex-handoff-guidance`
- Purpose: Own executor/runtime selection, prepared handoff payloads, and status narration while the chosen coding agent or runtime owns code changes.
- Owns:
  - Executor, runtime, or Hermes coding-skill choice
  - Prepared coding handoff with team/swarm, worker, worktree, acceptance, and verification expectations when relevant
  - Observed lifecycle status when a tested executor contract records it
- Primary skills: `ultragoal`, `ultrawork`, `ralph`, `ai-slop-cleaner`
- Primary harnesses: `goal-execution`, `parallel-delivery`, `coding-handling`
- Wrapper actions: `choose_executor`, `show_prompt_handoff`, `show_runtime_handoff`, `start_team`, `start_swarm`, `prepare_worktree`, `send_to_executor`, `show_status`
- Evidence boundary: A prepared coding handoff is not executor/runtime dispatch, worker start, worktree creation, result, verification, review, CI, merge readiness, or merge evidence. Hermes/OMX/OMO/OMC runtime handoffs must record separate `runtime_observation/v1` events before the status can move from prepared to observed.

### Builder

- ID: `builder`
- Display name: Builder
- Legacy aliases: `implementation-owner`
- Purpose: Name the implementation responsibility inside a prepared Hermes-facing playbook while the selected executor/runtime remains the actual work owner.
- Owns:
  - Presentation-layer implementation step in the prepared playbook
  - selected executor/runtime ownership narration
  - Expected implementation artifact boundary before observed evidence exists
- Primary skills: `ultragoal`, `ultrawork`, `ralph`
- Primary harnesses: `goal-execution`, `coding-handling`
- Wrapper actions: `choose_executor`, `show_prompt_handoff`, `show_runtime_handoff`, `send_to_executor`, `show_status`
- Evidence boundary: A builder role label is not hidden coding execution, executor/runtime dispatch, worker start, implementation result, verification, review, CI, merge readiness, or merge evidence. The selected executor/runtime owns implementation only after observed evidence exists.

### Tracker

- ID: `tracker`
- Display name: Tracker
- Legacy aliases: `hybrid-measurement`
- Purpose: Own runtime status, target topology, executor session, measurement, tool readiness, and observability narration.
- Owns:
  - Observed runtime, target, executor, and status-card state
  - Tool, MCP, credential, token, cost, latency, and run-history readiness gaps
  - Progress narration without upgrading missing evidence
- Primary skills: `performance-goal`, `agent-board`, `executor-runtime-readiness`, `toolbelt-readiness`, `ops-observability-card`, `doctor`, `skill`, `cancel`
- Primary harnesses: `measurement`, `status`, `tool-readiness`, `operator-health`
- Wrapper actions: `show_status`, `refresh_status`, `choose_executor`
- Evidence boundary: A tracker role can report status and missing evidence; it is not proof that an executor, worker, tool, MCP server, CI job, or platform action ran.

### Reviewer

- ID: `reviewer`
- Display name: Reviewer
- Legacy aliases: `review-gate`, `hybrid-review`, `hybrid-verification`
- Purpose: Own claim checking, review findings, QA framing, release/readiness review, and evidence requirements.
- Owns:
  - Findings and risks
  - Verification, CI, and release-readiness status
  - Follow-up handoff only when fixes are accepted
- Primary skills: `code-review`, `ultraqa`, `ask`
- Primary harnesses: `code-review`, `qa`, `ops-review`
- Wrapper actions: `show_findings`, `prepare_fix_handoff`, `refresh_status`
- Evidence boundary: Review findings are not fix evidence; merge-ready is not merged.

## Public Claim Rule

A role can explain responsibility and next action. A role does not prove execution, dispatch, review, CI, merge readiness, or merge evidence. Those claims require matching observed runtime or wrapper evidence.
