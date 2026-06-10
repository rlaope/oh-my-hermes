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

- `hermes skills tap add rlaope/oh-my-hermes-agent`, then `hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes` installs this tap-compatible skill pack directly when Hermes supports taps.
- `omh setup` installs generated managed skills and registers their directory through `skills.external_dirs` when a local bootstrap or repair path is preferred.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Skill Role Classification

Keep compatible workflow names installed, but use this advisory wrapper guidance to decide what Hermes should own:

- `codex-handoff-guidance`: `ralph`, `ultragoal`, `team`, `ultrawork`, `ai-slop-cleaner`
- `hybrid-measurement`: `performance-goal`
- `hybrid-review`: `code-review`, `ask`
- `hybrid-verification`: `ultraqa`
- `retained-cognition`: `loop`, `deep-interview`, `web-research`, `research-brief`, `strategy-brief`, `meeting-brief`, `feedback-triage`, `ops-review`, `idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `plan`, `ralplan`, `best-practice-research`, `autoresearch-goal`
- `retained-knowledge`: `wiki`
- `retained-operator`: `cancel`, `skill`, `doctor`
- `retained-router`: `oh-my-hermes`
- Full per-skill handoff policies live in generated workflow skills and `docs/WORKFLOWS.md`.

General rule: Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. This role metadata is advisory unless a wrapper/runtime artifact records observed enforcement. When the accepted next action mutates code, the wrapper should ask for or apply the selected executor profile, prepare the matching handoff, and track only evidence it actually observes instead of implying Hermes coded secretly.

## Multi-Agent Target Awareness

Wrappers may report `omh_target_topology/v1` when a workspace moves between one Hermes agent target and multiple Hermes agent targets. Treat that topology as setup evidence only. If `active_agent_count` is greater than one, bind this workflow to the current target and thread, name the target boundary in status, and do not claim another Hermes agent observed, accepted, or executed the workflow unless target-specific evidence exists.

If a wrapper reports `single_to_multi` or `multi_to_single`, answer with one concise target-change comment. If the wrapper exposes an `apply_target_change` action and the user accepts it, persist the target registry update; otherwise keep the workflow scoped to the current thread target and ask before assuming multi-agent behavior. A skill that does not need multiple agents should continue as a single-target workflow even when multiple targets are known.

## Responsibility Roles

Responsibility role details are generated in `docs/WORKFLOWS.md` and surfaced by `skill_view`. Use the compact role registry above in the router prompt to keep ordinary Hermes routing lightweight.

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
- `loop`: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`
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

- `coding-handling`: Route implementation requests through scoped context, edit discipline, tests, review, and evidence. Tier `handoff-gated`. Ladder: `coding_delegation_prepared` -> `executor_dispatch_observed` -> `executor_result_observed` -> `verification_recorded`. Actions: `accept_plan`, `show_prompt_handoff`, `copy_prompt_handoff`, `choose_executor`, `send_to_executor`. Privacy `metadata_only`.
- `goal-execution`: Keep long-running work tied to explicit goals, checkpoints, and durable evidence. Tier `checkpoint-gated`. Ladder: `goal_created` -> `story_started` -> `checkpoint_recorded` -> `quality_gate_recorded`. Actions: `continue_goal`, `show_status`, `record_checkpoint`, `record_blocker`, `record_completion`. Privacy `metadata_only`.
- `planning`: Turn clarified requirements into an execution-ready plan with tradeoffs and tests. Tier `acceptance-gated`. Ladder: `request_clarified` -> `plan_drafted` -> `option_tradeoffs_recorded` -> `test_strategy_recorded`. Actions: `accept_plan`, `revise_plan`, `cancel`, `prepare_handoff`. Privacy `metadata_only`.
- `research`: Gather current or source-backed evidence before planning or coding handoff. Tier `source-gated`. Ladder: `research_question_scoped` -> `primary_sources_checked` -> `conflicts_checked` -> `evidence_synthesized`. Actions: `show_sources`, `ask_followup`, `prepare_plan`. Privacy `metadata_only`.
- `business-research`: Prepare source-backed business research briefs with evidence and inference boundaries. Tier `source-gated`. Ladder: `business_question_scoped` -> `source_boundary_recorded` -> `source_evidence_recorded` -> `business_synthesis_recorded`. Actions: `show_sources`, `ask_followup`, `prepare_strategy_brief`, `show_status`. Privacy `metadata_only`.
- `strategy-synthesis`: Turn goals and evidence into strategy options, tradeoffs, and decision-ready notes. Tier `decision-gated`. Ladder: `decision_scope_recorded` -> `options_recorded` -> `tradeoffs_recorded` -> `recommendation_recorded`. Actions: `show_brief`, `revise_brief`, `record_decision`, `show_status`. Privacy `metadata_only`.
- `meeting-facilitation`: Prepare agendas, discussion prompts, decisions, and record templates. Tier `facilitation-gated`. Ladder: `meeting_goal_scoped` -> `agenda_recorded` -> `discussion_prompts_recorded` -> `decisions_needed_recorded`. Actions: `show_agenda`, `revise_brief`, `record_decision`, `show_status`. Privacy `metadata_only`.
- `customer-insight-triage`: Cluster customer feedback and choose the next workflow without defaulting to coding. Tier `triage-gated`. Ladder: `feedback_source_scoped` -> `clusters_recorded` -> `severity_opportunity_recorded` -> `next_workflow_recommended`. Actions: `show_triage`, `ask_followup`, `prepare_plan`, `show_status`. Privacy `metadata_only`.
- `ops-review`: Summarize observed operating status, risks, blockers, priorities, and follow-up actions. Tier `status-gated`. Ladder: `review_scope_recorded` -> `status_evidence_recorded` -> `risks_blockers_recorded` -> `priorities_recorded`. Actions: `show_status`, `record_blocker`, `record_checkpoint`, `prepare_plan`. Privacy `metadata_only`.
- `app-delivery-loop`: Run complete app operation loops from idea through decision, handoff, release, deploy, and monitor status. Tier `delivery-gated`. Ladder: `loop_scope_recorded` -> `decision_gate_recorded` -> `plan_or_release_gate_accepted` -> `handoff_prepared_if_needed`. Actions: `show_delivery_loop`, `accept_plan`, `choose_executor`, `prepare_handoff`, `record_deploy`. Privacy `metadata_only`.
- `goal-loop`: Run ambitious goal loops through task discovery, distribution, execution, verification, next-task decisions, runtime ticks with deterministic queue shapes, handoff, feedback, waiting, and resumable status without hidden execution. Tier `loop-gated`. Ladder: `loop_triggered` -> `goal_reframed` -> `permission_profile_recorded` -> `runtime_tick_queued`. Actions: `choose_permission_profile`, `start_loop`, `run_loop_tick`, `show_loop_queue`, `prepare_loop_handoff`. Privacy `metadata_only`.
- `deep-interview`: Clarify intent and boundaries one question at a time before planning or execution. Tier `clarity-gated`. Ladder: `ambiguity_identified` -> `blocking_question_asked` -> `answer_recorded` -> `clarified_brief_ready`. Actions: `answer:clarify`, `cancel`, `rerun_plan`. Privacy `metadata_only`.
- `architect`: Evaluate system boundaries, integration choices, and long-term maintainability. Tier `boundary-gated`. Ladder: `architecture_context_loaded` -> `tradeoffs_recorded` -> `boundary_verdict_recorded`. Actions: `show_review`, `revise_plan`, `approve_plan`. Privacy `metadata_only`.
- `critic`: Challenge plan consistency, quality criteria, and missing verification. Tier `finding-gated`. Ladder: `review_scope_loaded` -> `findings_recorded` -> `verdict_recorded` -> `residual_risk_recorded`. Actions: `show_findings`, `request_changes`, `approve_plan`. Privacy `metadata_only`.
- `qa-specialist`: Design adversarial scenarios and verify user-visible behavior before completion. Tier `scenario-gated`. Ladder: `scenario_matrix_defined` -> `checks_run` -> `pass_fail_recorded` -> `fix_followup_recorded_if_needed`. Actions: `show_status`, `record_check`, `record_blocker`. Privacy `metadata_only`.
- `docs-specialist`: Keep public docs accurate, installable, and aligned with actual behavior. Tier `claim-gated`. Ladder: `claims_scoped` -> `docs_updated` -> `generated_docs_checked` -> `public_claims_verified`. Actions: `show_docs`, `record_claim_check`, `show_status`. Privacy `metadata_only`.

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
