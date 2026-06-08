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

- `oh-my-hermes`: role `retained-router`; handoff policy: Classify requests into Hermes-retained planning/research/interview lanes, executor choice, or prepared coding handoffs; do not execute code.
- `ralph`: role `codex-handoff-guidance`; handoff policy: Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track the selected executor path instead of making Hermes the hidden coder.
- `ultragoal`: role `codex-handoff-guidance`; handoff policy: Use Hermes to maintain durable goal/checkpoint state; delegate coding milestones to the selected coding executor and report only observed runtime evidence.
- `deep-interview`: role `retained-cognition`; handoff policy: Run directly in Hermes or the chat wrapper; produce a clarified brief before any coding handoff is prepared.
- `team`: role `codex-handoff-guidance`; handoff policy: Use Hermes for lane framing and status; implementation lanes should become selected executor handoff tasks unless they are research, interview, planning, or status-only.
- `ultrawork`: role `codex-handoff-guidance`; handoff policy: Keep the workflow name for compatibility, but convert coding lanes into explicit selected executor handoffs with disjoint scope, verification, and review evidence.
- `web-research`: role `retained-cognition`; handoff policy: Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.
- `research-brief`: role `retained-cognition`; handoff policy: Keep business research in Hermes; prepare a selected executor handoff only after a later accepted plan requires code changes.
- `strategy-brief`: role `retained-cognition`; handoff policy: Keep strategy synthesis in Hermes; do not create implementation handoff until a decision is accepted and code work is explicit.
- `meeting-brief`: role `retained-cognition`; handoff policy: Run meeting preparation in Hermes; only create follow-up coding handoff from observed decisions or accepted plans.
- `feedback-triage`: role `retained-cognition`; handoff policy: Keep feedback triage in Hermes; recommend the next workflow and prepare a selected executor handoff only after explicit coding intent or accepted plan evidence.
- `ops-review`: role `retained-cognition`; handoff policy: Keep operating review and status narration in Hermes; delegate code fixes only from explicit accepted follow-up items.
- `idea-to-deploy`: role `retained-cognition`; handoff policy: Keep idea shaping, decision gates, planning, release narration, and status in Hermes; prepare selected executor handoffs only for accepted code work and record deploy/monitoring only from observed operator or wrapper evidence.
- `cto-loop`: role `retained-cognition`; handoff policy: Keep CTO/PM-style synthesis, tradeoffs, risk ranking, decision notes, and status in Hermes; convert accepted implementation follow-ups into executor-neutral handoffs.
- `deploy-and-monitor`: role `retained-cognition`; handoff policy: Keep release checklist, health criteria, rollback gates, and status narration in Hermes; record deploy, monitor, incident, or rollback evidence only when the wrapper or operator observes it.
- `ultraqa`: role `hybrid-verification`; handoff policy: Hermes can design scenarios and report observed results; code fixes discovered by QA should become selected executor handoffs.
- `plan`: role `retained-cognition`; handoff policy: Keep planning in Hermes; if the accepted plan requires code edits, prepare a selected executor handoff after acceptance.
- `ralplan`: role `retained-cognition`; handoff policy: Keep consensus planning and review in Hermes; produce explicit selected executor handoff guidance only after the plan is accepted.
- `code-review`: role `hybrid-review`; handoff policy: Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to the selected coding executor.
- `ai-slop-cleaner`: role `codex-handoff-guidance`; handoff policy: Use Hermes to define cleanup scope and regression checks; delegate behavior-preserving edits to the selected coding executor once tests are clear.
- `best-practice-research`: role `retained-cognition`; handoff policy: Run as Hermes-side evidence gathering; hand coding to the selected executor only after source-backed guidance is summarized.
- `autoresearch-goal`: role `retained-cognition`; handoff policy: Keep durable research in Hermes-managed artifacts; do not convert to executor handoff unless the research produces an accepted coding task.
- `performance-goal`: role `hybrid-measurement`; handoff policy: Hermes can own baselines, benchmark plans, and status; optimization code changes should be selected executor handoffs.
- `wiki`: role `retained-knowledge`; handoff policy: Run directly in Hermes as knowledge capture unless the note reveals a separate coding task.
- `ask`: role `hybrid-review`; handoff policy: Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.
- `cancel`: role `retained-operator`; handoff policy: Run directly in Hermes/runtime state; never delegate cancellation to a coding executor.
- `skill`: role `retained-operator`; handoff policy: Use Hermes for inventory and guidance; delegate only repository code changes to the selected coding executor.
- `doctor`: role `retained-operator`; handoff policy: Run directly as local health inspection; propose executor work only when a repo fix is required.

General rule: Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. This role metadata is advisory unless a wrapper/runtime artifact records observed enforcement. When the accepted next action mutates code, the wrapper should ask for or apply the selected executor profile, prepare the matching handoff, and track only evidence it actually observes instead of implying Hermes coded secretly.

## Multi-Agent Target Awareness

Wrappers may report `omh_target_topology/v1` when a workspace moves between one Hermes agent target and multiple Hermes agent targets. Treat that topology as setup evidence only. If `active_agent_count` is greater than one, bind this workflow to the current target and thread, name the target boundary in status, and do not claim another Hermes agent observed, accepted, or executed the workflow unless target-specific evidence exists.

If a wrapper reports `single_to_multi` or `multi_to_single`, answer with one concise target-change comment. If the wrapper exposes an `apply_target_change` action and the user accepts it, persist the target registry update; otherwise keep the workflow scoped to the current thread target and ask before assuming multi-agent behavior. A skill that does not need multiple agents should continue as a single-target workflow even when multiple targets are known.

## Responsibility Roles

OMH role names are responsibility descriptors, not runtime agents. They help Hermes and wrappers explain who owns the next step without implying a hidden worker ran.

- `research-lead` (Research Lead): Own source-backed discovery and keep evidence, inference, confidence, and unknowns separate.
  - Skills: `web-research`, `best-practice-research`, `research-brief`, `autoresearch-goal`
  - Evidence boundary: A research role can prepare or summarize evidence; it is not implementation, review, CI, or merge evidence.
- `planning-lead` (Planning Lead): Own clarification, non-goals, acceptance criteria, tradeoffs, and verification strategy.
  - Skills: `deep-interview`, `plan`, `ralplan`, `strategy-brief`
  - Evidence boundary: A planning role can make work reviewable; it is not proof that the work was accepted or executed.
- `review-gate` (Review Gate): Own claim checking, release/readiness review, QA framing, and evidence requirements.
  - Skills: `code-review`, `ultraqa`, `ops-review`
  - Evidence boundary: Review findings are not fix evidence; merge-ready is not merged.
- `coding-handoff` (Coding Handoff): Own executor selection, prepared handoff payloads, and status narration while selected executors own code changes.
  - Skills: `ultragoal`, `ultrawork`, `ralph`, `ai-slop-cleaner`
  - Evidence boundary: A prepared coding handoff is not executor dispatch, result, verification, review, CI, merge readiness, or merge evidence.

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
omh coding delegate --source discord --executor codex --record "risky refactor"
```

The command returns a `coding_delegation/v1` payload with a recommended workflow, harness, executor profile, acceptance criteria, verification expectations, and a `delegation_prompt_template` that the wrapper can forward with the user message substituted. It is deterministic and uses only local catalog metadata. Without an explicit executor, wrappers can receive an executor-choice response; non-Codex executors receive prompt-only handoffs unless a tested lifecycle contract exists.

With `--record`, `omh` creates a `.omh/runtime/runs/<run-id>/` prepared runtime run only for a Codex-selected delegate payload that contains a real `executor_handoff`. Executor-choice, prompt-only, retained-Hermes, clarify, and fallback responses return `runtime.recorded=false` and must stay wrapper/session state rather than prepared run evidence. For Codex runs, `coding_delegation.json` is paired with `run.json` marked `status: prepared`, `artifact_kind: prepared_coding_delegation`, `phase: prepared`, and `observation_status: prepared_not_observed`. These artifacts store only allowlisted metadata, acceptance criteria, verification expectations, recommendation evidence, source references, `message_sha256`, and `message_length`. They mean a coding handoff was prepared; they do not mean Hermes executed the work or that a specialist lane was observed.

## Wrapper Backend Memory Context

Wrappers can run `omh memory inspect`, `omh memory pack`, and `omh memory apply` to review OMH-local or wrapper-supplied context before preparing a handoff. This emits `memory_review_card/v1` and `handoff_context_pack/v1` artifacts only; it does not read or mutate opaque Hermes internal memory. A context pack may be attached to an executor handoff only when unresolved conflicts are absent.

## Hermes-Facing Planning

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to create a deterministic `hermes_plan/v1` planning scaffold. In normal chat, Hermes can express this plan directly through the installed skill guidance:

```sh
omh hermes plan --source discord --record "risky refactor with review"
```

With `--record`, `omh` writes a Markdown draft under `.hermes/plans/`. Weak requests also write `.hermes/context/` so Hermes can ask one blocking clarification before a final plan. The plan includes goals, non-goals, options, risks, acceptance criteria, verification, execution handoff guidance, and a review gate. Review gate entries default to `not_observed`; do not call the plan approved unless wrapper or human evidence proves the review happened.

The stdout `wrapper_contract` is the adapter contract for follow-on wrapper work. Use it instead of parsing the Markdown file. For implementation-shaped draft plans, `wrapper_contract.coding_delegate.argv_template` gives the exact `omh coding delegate --executor codex --record` argv shape for a run-backed Codex handoff after plan acceptance. For blocked or non-coding plans, `coding_delegate.available` is `false`; follow `wrapper_contract.next_action` and do not dispatch a coding handoff.

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

- `ralph`: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- `ultragoal`: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
- `deep-interview`: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`
- `team`: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- `ultrawork`: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- `web-research`: `web-research`, `web research`, `latest`, `current sources`, `source-backed research`
- `research-brief`: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`
- `strategy-brief`: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`
- `meeting-brief`: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`
- `feedback-triage`: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`
- `ops-review`: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`
- `idea-to-deploy`: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`
- `cto-loop`: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`
- `deploy-and-monitor`: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`
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
  - Wrapper Actions: `accept_plan`, `show_prompt_handoff`, `copy_prompt_handoff`, `choose_executor`, `send_to_executor`, `send_to_codex`, `show_status`, `record_result`
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
- `business-research`: Prepare source-backed business research briefs with evidence and inference boundaries.
  - Use when: Use when a business, market, customer, or operational question needs source-scoped research before strategy, meetings, or handoff.
  - Quality tier: `source-gated`
  - Inputs: business question, source boundary, recency or market scope
  - Outputs: evidence table, inference summary, confidence and residual uncertainty
  - Quality Bar: Scope the business question and source boundary before synthesis. Separate observed sources, inferred trends, confidence, and uncertainty. Feed strategy or meeting work without treating the research brief as execution evidence.
  - Evidence Ladder: `business_question_scoped` -> `source_boundary_recorded` -> `source_evidence_recorded` -> `business_synthesis_recorded` -> `uncertainty_recorded`
  - Wrapper Actions: `show_sources`, `ask_followup`, `prepare_strategy_brief`, `show_status`
  - Verification: check source quality, record missing-source gaps
  - Runtime Evidence: events `business_research_scoped`, `business_source_checked`, `business_synthesis_recorded`; privacy `metadata_only`
  - Delegation: Record business research only when Hermes or the wrapper observes sources or captures a research brief.
  - Overclaim Guards: A research brief is not proof that sources were fetched unless source evidence is observed. Research synthesis is not a decision, implementation, or verification result.
  - Fallback: If sources are not available, label the result as a research plan or local-context synthesis rather than observed research.
- `strategy-synthesis`: Turn goals and evidence into strategy options, tradeoffs, and decision-ready notes.
  - Use when: Use when the request asks for strategy, recommendations, decision notes, or leadership-ready synthesis.
  - Quality tier: `decision-gated`
  - Inputs: goal, evidence summary, constraints
  - Outputs: options, tradeoffs, recommendation
  - Quality Bar: Name the decision, drivers, options, tradeoffs, recommendation, and assumptions. Keep draft recommendations separate from accepted decisions. Convert implementation follow-ups into explicit later plans or handoffs.
  - Evidence Ladder: `decision_scope_recorded` -> `options_recorded` -> `tradeoffs_recorded` -> `recommendation_recorded` -> `decision_status_recorded`
  - Wrapper Actions: `show_brief`, `revise_brief`, `record_decision`, `show_status`
  - Verification: compare options, tie recommendation to evidence
  - Runtime Evidence: events `strategy_scope_recorded`, `options_recorded`, `decision_note_recorded`; privacy `metadata_only`
  - Delegation: Record strategy synthesis as Hermes-retained work; record execution only after a later accepted handoff is observed.
  - Overclaim Guards: A strategy brief is not an accepted decision. A recommendation is not implementation, review, CI, or merge evidence.
  - Fallback: If decision authority or evidence is missing, produce assumptions and next questions instead of a final decision.
- `meeting-facilitation`: Prepare agendas, discussion prompts, decisions, and record templates.
  - Use when: Use when the request asks Hermes to prepare a meeting, agenda, discussion guide, or follow-up record template.
  - Quality tier: `facilitation-gated`
  - Inputs: meeting goal, audience, context
  - Outputs: agenda, discussion prompts, decisions needed
  - Quality Bar: Prepare agenda topics, prompts, decisions needed, and a record template from available context. Keep proposed agenda and action items separate from observed meeting outcomes. Ask for missing context that would change participants, decisions, or timing.
  - Evidence Ladder: `meeting_goal_scoped` -> `agenda_recorded` -> `discussion_prompts_recorded` -> `decisions_needed_recorded` -> `record_template_ready`
  - Wrapper Actions: `show_agenda`, `revise_brief`, `record_decision`, `show_status`
  - Verification: check missing context, separate prep from outcomes
  - Runtime Evidence: events `meeting_context_scoped`, `agenda_recorded`, `record_template_recorded`; privacy `metadata_only`
  - Delegation: Record meeting prep only as prepared content unless observed meeting notes or decisions are supplied.
  - Overclaim Guards: A prepared agenda is not evidence that a meeting happened. Draft action items are not observed decisions.
  - Fallback: If the meeting already happened, ask for observed notes before treating decisions as outcomes.
- `customer-insight-triage`: Cluster customer feedback and choose the next workflow without defaulting to coding.
  - Use when: Use when feedback, bugs, feature asks, or customer signals need classification before planning or implementation.
  - Quality tier: `triage-gated`
  - Inputs: feedback items or summary, source boundary, product area
  - Outputs: clusters, severity or opportunity ranking, next workflow recommendation
  - Quality Bar: Scope the feedback source before clustering. Separate bug signals, feature asks, severity, opportunity, and evidence gaps. Recommend research, strategy, planning, or coding only as a next workflow, not as observed execution.
  - Evidence Ladder: `feedback_source_scoped` -> `clusters_recorded` -> `severity_opportunity_recorded` -> `next_workflow_recommended`
  - Wrapper Actions: `show_triage`, `ask_followup`, `prepare_plan`, `show_status`
  - Verification: separate bug signals from feature asks, rank severity and opportunity
  - Runtime Evidence: events `feedback_source_scoped`, `feedback_cluster_recorded`, `next_workflow_recorded`; privacy `metadata_only`
  - Delegation: Record feedback triage as Hermes-retained analysis; record coding handoff only after explicit accepted coding intent.
  - Overclaim Guards: Feedback triage is not a roadmap, implementation plan, or coding handoff by default. A bug signal is not proof that a fix was implemented or verified.
  - Fallback: If feedback items are too vague, ask for source or sample items before ranking severity.
- `ops-review`: Summarize observed operating status, risks, blockers, priorities, and follow-up actions.
  - Use when: Use when recurring work needs a weekly/status/operating review with evidence boundaries.
  - Quality tier: `status-gated`
  - Inputs: status evidence, scope, time window
  - Outputs: status summary, risks, blockers
  - Quality Bar: Tie status claims to observed evidence or mark them as unknown. Separate risks, blockers, priorities, and follow-up actions. Do not infer review, CI, release, or merge readiness from an ops summary alone.
  - Evidence Ladder: `review_scope_recorded` -> `status_evidence_recorded` -> `risks_blockers_recorded` -> `priorities_recorded` -> `followups_recorded`
  - Wrapper Actions: `show_status`, `record_blocker`, `record_checkpoint`, `prepare_plan`
  - Verification: check evidence gaps, separate facts from risks
  - Runtime Evidence: events `ops_scope_recorded`, `status_recorded`, `followups_recorded`; privacy `metadata_only`
  - Delegation: Record ops review as Hermes-retained status work; execution evidence requires later observed task records.
  - Overclaim Guards: An ops review is not release, CI, review, merge, or implementation evidence. Missing evidence must stay unknown, not inferred green.
  - Fallback: If evidence is missing, produce a review scaffold and mark unknowns instead of claiming status.
- `app-delivery-loop`: Run complete app operation loops from idea through decision, handoff, release, deploy, and monitor status.
  - Use when: Use when a Hermes wrapper needs a finished-product-feeling path for idea-to-deploy, CTO loops, or deploy-and-monitor work without hidden coding or infrastructure execution.
  - Quality tier: `delivery-gated`
  - Inputs: idea or release request, success metric, scope constraints
  - Outputs: stage rail, decision gates, handoff or retained-work plan
  - Quality Bar: Name the product or release objective, user/customer value, success metric, non-goals, and owner. Represent idea, decision, plan, handoff, verification, release, deploy, and monitor as separate stages. Keep coding work executor-neutral until a selected executor is chosen and a handoff is accepted. Keep deploy, monitoring, rollback, incident, review, CI, and merge claims unavailable until observed evidence exists.
  - Evidence Ladder: `loop_scope_recorded` -> `decision_gate_recorded` -> `plan_or_release_gate_accepted` -> `handoff_prepared_if_needed` -> `verification_release_gate_recorded` -> `deploy_monitor_observed_when_available`
  - Wrapper Actions: `show_delivery_loop`, `accept_plan`, `choose_executor`, `prepare_handoff`, `record_deploy`, `record_monitor_signal`, `show_status`
  - Verification: check every stage has an owner, separate prepared from observed
  - Runtime Evidence: events `delivery_loop_scoped`, `decision_gate_recorded`, `handoff_or_release_status_recorded`; privacy `metadata_only`
  - Delegation: Record app delivery loop evidence only when Hermes, a wrapper, or an operator observes stage acceptance, handoff, deploy, or monitoring events.
  - Overclaim Guards: A prepared app delivery loop is not implementation, deploy, monitor, rollback, incident, review, CI, merge-readiness, or merge evidence. A CTO loop recommendation is not an accepted decision unless decision evidence is recorded. A health watchlist is not observed health evidence.
  - Fallback: If release scope, owner, or evidence is missing, show the loop scaffold and ask for the smallest missing decision before advancing.
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
omh coding delegate --source discord --executor codex --record "risky refactor"
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record only what is observed. A Codex-selected `coding_delegation.json` record and its `prepared_coding_delegation` run envelope prove a prepared handoff, not execution. Executor-choice and prompt-only handoffs do not create runtime runs. If Hermes does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.
