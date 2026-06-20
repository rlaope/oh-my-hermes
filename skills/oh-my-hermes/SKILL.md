---
name: oh-my-hermes
description: [omh] Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, router]
    category: router
    phase: routing
    role: guide
    quality_tier: routing-gated
---

# Oh My Hermes Router

Use this skill when the user mentions oh-my-hermes or a workflow keyword such as `deep-interview`, `ralplan`, `ultragoal`, `loop`, `ultraprocess`, `web-research`, `research-department`, `feedback-triage`, `materials-package`, `img-summary`, `automation-blueprint`, `workflow-learning`, `code-review`, `team`, `ultrawork`, `ultraqa`, `doctor`.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact runtime parity with another agent framework.

Normal users should talk to Hermes Agent or invoke installed Hermes skills through Hermes' own skill surface. Do not ask chat users to run `omh` commands for ordinary workflow use. The `omh` command is bootstrap, maintenance, verification, and wrapper/backend infrastructure.

## Why This Exists

`oh-my-hermes` exists to keep Hermes chat routing conservative: it maps plain requests to the right workflow, explains evidence boundaries, and avoids making every keyword look like hidden implementation.

## Do Not Use When

- The user already invoked a more specific installed skill and its routing signals are unambiguous.
- The message is ordinary chat, status acknowledgement, or a question that does not need workflow routing.
- The wrapper wants to claim execution, review, CI, or merge evidence that no observed artifact provides.

## Examples

Good example:

- Prompt: Use OMH request-to-handoff for: safely add a feature to this repo.
- Expected behavior: Classify the request, name the retained Hermes lane or prepared coding handoff, and expose the observed/prepared evidence boundary.
- Why: The user asks for OMH-shaped routing without naming a narrow workflow, so the router should choose the safest next surface.

Bad example:

- Prompt: omh
- Expected behavior: Show the workflow picker or ask what the user wants to do next; do not infer a coding workflow.
- Why: A bare product name is a picker or clarification signal, not implementation evidence.

## Completion Checklist

- The selected workflow, confidence reason, evidence boundary, and user-facing next action are named.
- Low-confidence or conflicting signals return a picker or clarification instead of forced routing.
- Catalog answers are rendered without shell approval when wrapper metadata is sufficient.

## Recovery Notes

- If routing signals conflict, show the compact picker or ask one clarifying question.
- If wrapper metadata is unavailable, keep the recommendation advisory and avoid runtime claims.

## OMH Awareness Primer

OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off without hiding unobserved execution.

When a request asks for planning, research, ops records, files/materials, visual summaries, image cards, automation, coding delegation, review, status, or long-running loops, consider OMH before generic chat or generic tools.

Across every OMH skill: match intent to a lane, name adjacent workflows, and do not dismiss OMH because a generic tool can render or execute.

Before generic tools, check OMH prep/status/learning; if relevant, name the workflow first.

Every generated workflow skill carries this rail.

Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- **Intent -> plan**: ambiguous goals, plans, one-cycle delivery, durable goals, and loopable projects. Key: `oh-my-hermes`, `deep-interview`, `plan`, `ralplan`.
- **Research and company ops**: source-backed research, customer signals, product operations, and briefing workflows. Key: `web-research`, `best-practice-research`, `autoresearch-goal`, `research-brief`.
- **Materials and visual summaries**: decks, PDFs, spreadsheets, documents, image summary cards, and shareable packages. Key: `materials-package`, `img-summary`, `report-package`, `deliverable-package`.
- **Automation and status**: scheduled ops, gateway cards, boards, tool readiness, status, health, and release/ops review. Key: `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`.
- **Coding handoff**: Codex, Claude Code, Hermes coding, or oh-my runtime paths with observed evidence tracking. Key: `idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `code-review`.

Workflow context cards:
intent -> deep-interview/ralplan/loop/ultraprocess; signals -> web-research/research-department/feedback-triage/meeting-brief; materials -> materials-package/report-package/img-summary; automation/status/learning -> automation-blueprint/agent-ops-review/workflow-learning/doctor; code -> ultraprocess/code-review/team/ultrawork/ultraqa.

Common cues before generic tools:
notes/retros -> operating-rhythm/meeting-brief; PR/issue/bug/feedback/release -> github-event-ops, feedback-triage, report-package, or img-summary; sources/news -> web-research or research-department; decks/PDF/sheets/docs/HWP -> materials-package or report-package; image cards/infographics -> img-summary; coding/status/review/CI/merge -> ultraprocess, code-review, or agent-ops-review; trace/improve/regression -> workflow-learning.

Generic tool map:
image->img-summary; file->materials-package; search->web-research; code->ultraprocess/ralplan/review.

Tools:
- Tools: `omh_interact`; `omh_context`; `omh_recommend`; `omh_capabilities`; `omh_probe`; `omh_status`/`omh_hud`; `omh_role`.

If an external image tool, coding agent, connector, credential, or runtime is missing, offer setup/selection fallback instead of claiming the action happened.

Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Direct Picker Aliases

If the user has only typed `./`, `/`, `./o`, or `/om`, show a command preview with exactly one top-level suggestion: `omh`. Selecting it should insert `./omh` or `/omh` and then open the workflow picker. Do not preview every installed workflow at the first `./` stage.

For messenger-native setup, wrappers can call `omh chat native-command --source discord`, `--source slack`, or `--source telegram` to get the platform command/menu registration contract. When plain-message autocomplete is not available, render the returned `omh_command_fallback_card/v1` as an `Open omh` button/card before opening the picker.

If the user types `./omh`, `/omh`, `./skills`, or `/skills` without a task, show a compact workflow picker instead of creating a plan. Keep real skill names unchanged; present options such as `deep-interview`, `ralplan`, `loop`, `ultraprocess`, `feedback-triage`, `web-research`, `research-department`, `code-review`, `materials-package`, `automation-blueprint`, and `doctor`.

In Discord, Slack, or similar wrappers, render `chat_response.state.skill_picker.featured_options` first, then `chat_response.state.skill_picker.groups` as short sections. Keep `chat_response.state.skill_picker.options` as a backward-compatible flat-list fallback. In Hermes TUI, render the same grouped sections as a compact command list. Choosing a skill is routing intent, not plan acceptance, dispatch, execution, or verification evidence.

Hermes-native install paths should converge on the same skill-visible state:

- `hermes skills tap add rlaope/oh-my-hermes`, then `hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes` installs this tap-compatible skill pack directly when Hermes supports taps.
- `omh setup` installs generated managed skills and registers their directory through `skills.external_dirs` when a local bootstrap or repair path is preferred.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Skill Role Classification

Use installed primary workflow skills plus compatibility surfaces in this registry as advisory wrapper guidance to decide what Hermes should own:

- `guide`: `oh-my-hermes`, `gateway-intent-card`, `voice-operator`
- `handoff-guide`: `ralph`, `ultragoal`, `ultraprocess`, `team`, `ultrawork`, `ai-slop-cleaner`, `executor-runtime-readiness`
- `memory-keeper`: `wiki`, `memory-curation-review`
- `operator`: `strategy-brief`, `meeting-brief`, `feedback-triage`, `ops-review`, `operating-rhythm`, `report-package`, `materials-package`, `img-summary`, `automation-blueprint`, `reliability-review`, `idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `github-event-ops`, `deliverable-package`
- `planner`: `loop`, `deep-interview`, `plan`, `ralplan`
- `researcher`: `web-research`, `research-brief`, `research-department`, `best-practice-research`, `autoresearch-goal`
- `reviewer`: `ultraqa`, `code-review`, `ask`
- `tracker`: `performance-goal`, `cancel`, `skill`, `doctor`, `agent-board`, `toolbelt-readiness`, `ops-observability-card`, `agent-ops-review`, `workflow-learning`
- Installed workflow skill policies live in generated workflow skills; compatibility/reference-only surface policies live in `docs/WORKFLOWS.md` and are not guaranteed to have `skills/<name>/SKILL.md` files.

General rule: Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. This role metadata is advisory unless a wrapper/runtime artifact records observed enforcement. When the accepted next action mutates code, the wrapper should ask for or apply the selected executor/runtime profile, prepare the matching handoff, and track only evidence it actually observes instead of implying code ran secretly.

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

If the user gives a natural-language request and Hermes needs the nearest OMH workflow, prefer `omh_interact` when the plugin/tool surface is available because it returns `chat_interaction/v1` and records a metadata-only wrapper session. Use `omh_recommend` only when Hermes needs route hints without a session record. If the user asks what OMH commands, skills, or workflows are available, prefer `omh_capabilities` with `action=summary`, or use `omh chat interact` and render `chat_response.kind == skill_picker` from a wrapper backend. If the user asks what to do next after OMH setup or install, use `omh_interact` or `omh chat interact` and render `chat_response.kind == quickstart`; it carries `omh_quickstart_card/v1`, first-use prompts, and the capability roadmap without shell approval. If the user explicitly asks for detailed status or health, prefer `omh_probe` with `include_roadmap=true` or render `chat_response.kind == status`. Do not make the user approve `omh list` just to see the catalog; the summary, picker, quickstart, and probe responses carry workflow options, next actions, and claim boundaries that selection or setup guidance is routing/status intent only.

This is a deterministic wrapper-side decision layer. By default, stdout and runtime artifacts avoid duplicating the raw prompt body. It does not patch Hermes core or require platform network access from `omh`.

## Wrapper Backend Coding Delegation

When a chat message is implementation-shaped and the wrapper wants a concrete executor handoff, run `omh coding delegate` after or instead of generic chat routing. This prepares adapter data; Hermes still narrates the user-facing state:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
```

The command returns a `coding_delegation/v1` payload with a recommended workflow, harness, executor/runtime profile, acceptance criteria, verification expectations, and a `delegation_prompt_template` that the wrapper can forward with the user message substituted. It is deterministic and uses only local catalog metadata. Without an explicit executor, wrappers can receive an executor-choice response; Codex receives a lifecycle handoff, Claude Code and generic agents receive portable prompt handoffs, and Hermes/OMX/OMO/OMC receive `coding_runtime_handoff/v1` contracts with team/swarm, worker-protocol, and worktree guidance.

The same payload includes `executor_readiness/v1`. Wrappers can run `omh coding executor-readiness --executor <profile>` on first use of Codex, Claude Code, or an oh-my runtime profile, then cache the result. If the probe reports `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or use a prompt/runtime handoff; after that state change, retry at most once. A readiness probe is not dispatch, execution, verification, review, CI, or merge evidence.

With `--record`, `omh` creates a `.omh/runtime/runs/<run-id>/` prepared runtime run only for a Codex-selected delegate payload that contains a real `executor_handoff`. Executor-choice, prompt-only, runtime-handoff, clarify, and fallback responses return `runtime.recorded=false` and must stay wrapper/session state rather than prepared run evidence. For Codex runs, `coding_delegation.json` is paired with `run.json` marked `status: prepared`, `artifact_kind: prepared_coding_delegation`, `phase: prepared`, and `observation_status: prepared_not_observed`. These artifacts store only allowlisted metadata, acceptance criteria, verification expectations, recommendation evidence, source references, `message_sha256`, and `message_length`. They mean a coding handoff was prepared; they do not mean Hermes executed the work or that a specialist lane was observed.

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
- `loop`: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan ultragoal feedback`
- `ultraprocess`: `ultraprocess`, `$ultraprocess`, `./ultraprocess`, `/ultraprocess`, `single-cycle delivery`, `one-cycle delivery`, `end-to-end process`
- `deep-interview`: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`
- `team`: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- `ultrawork`: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- `web-research`: `web-research`, `web research`, `web search`, `search the web`, `internet search`, `latest`, `fresh sources`
- `research-brief`: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`
- `research-department`: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`
- `strategy-brief`: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`
- `meeting-brief`: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`
- `feedback-triage`: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`
- `ops-review`: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`
- `operating-rhythm`: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`
- `report-package`: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`
- `materials-package`: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`
- `img-summary`: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image generation`, `image generation features`, `image generation support`
- `automation-blueprint`: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`
- `reliability-review`: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`
- `idea-to-deploy`: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`
- `cto-loop`: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`
- `deploy-and-monitor`: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`
- `ultraqa`: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`
- `plan`: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`, `safe feature`, `safely add a feature`
- `ralplan`: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`
- `code-review`: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`
- `ai-slop-cleaner`: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `behavior-preserving refactor`
- `best-practice-research`: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- `autoresearch-goal`: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- `performance-goal`: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- `wiki`: `wiki`, `project wiki`, `memory`, `notes`
- `ask`: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- `cancel`: `cancel`, `$cancel`, `stop`, `abort`
- `skill`: `skill`, `$skill`, `skills`, `manage skills`
- `doctor`: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- `github-event-ops`: `github-event-ops`, `github event ops`, `pr opened`, `ci failed`, `issue opened`, `pull request webhook`, `github webhook`
- `agent-board`: `agent-board`, `agent board`, `kanban`, `multi agent board`, `multiple hermes agents`, `multiple hermes profiles`, `hermes profiles`
- `memory-curation-review`: `memory-curation-review`, `memory curation`, `memory review`, `memory inspect`, `memory context review`, `context review`, `context cleanup`
- `gateway-intent-card`: `gateway-intent-card`, `gateway intent`, `discord thread`, `slack thread`, `telegram delivery`, `session delivery`, `silent update`
- `executor-runtime-readiness`: `executor-runtime-readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `executor tools`, `missing tools`, `handoff mode`
- `deliverable-package`: `deliverable-package`, `deliverable mode`, `file attachment`, `attach file`, `attachment status`, `file delivery`, `file deliverable status`
- `voice-operator`: `voice-operator`, `voice operator`, `voice-first`, `mobile command`, `short command`, `spoken request`, `accessibility`
- `toolbelt-readiness`: `toolbelt-readiness`, `mcp readiness`, `tool readiness`, `connector readiness`, `needed mcp`, `api credential`, `missing cli`
- `ops-observability-card`: `ops-observability-card`, `observability card`, `cost telemetry`, `latency telemetry`, `token telemetry`, `run history`, `loop telemetry`
- `agent-ops-review`: `agent-ops-review`, `agent ops review`, `agent productivity`, `operator productivity`, `manager view`, `quality dashboard`, `throughput review`
- `workflow-learning`: `workflow-learning`, `workflow learning`, `learning trace`, `learning audit`, `audit learning`, `learning review`, `review queue`

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.

## Representative Harness Registry

Use these harnesses to shape the response before adding new skills. They are quality lanes, not proof that a separate runtime role exists.

- `coding-handling`: Route implementation requests through scoped context, edit discipline, tests, review, and evidence. Tier `handoff-gated`. Ladder: `coding_delegation_prepared` -> `executor_dispatch_observed` -> `executor_result_observed` -> `verification_recorded` -> `review_ci_merge_recorded_when_required`. Actions: `accept_plan`, `show_prompt_handoff`, `copy_prompt_handoff`, `show_runtime_handoff`, `show_coding_team_path`, `start_runtime`. Privacy `metadata_only`.
- `goal-execution`: Keep long-running work tied to explicit goals, checkpoints, and durable evidence. Tier `checkpoint-gated`. Ladder: `goal_created` -> `story_started` -> `checkpoint_recorded` -> `quality_gate_recorded` -> `goal_closed`. Actions: `continue_goal`, `show_status`, `record_checkpoint`, `record_blocker`, `record_completion`. Privacy `metadata_only`.
- `planning`: Turn clarified requirements into an execution-ready plan with tradeoffs and tests. Tier `acceptance-gated`. Ladder: `request_clarified` -> `plan_drafted` -> `option_tradeoffs_recorded` -> `test_strategy_recorded` -> `acceptance_recorded` -> `handoff_ready`. Actions: `accept_plan`, `revise_plan`, `cancel`, `prepare_handoff`. Privacy `metadata_only`.
- `research`: Gather current or source-backed evidence before planning or coding handoff. Tier `source-gated`. Ladder: `research_question_scoped` -> `source_boundaries_recorded` -> `primary_sources_checked` -> `source_diversity_checked` -> `conflicts_checked` -> `evidence_synthesized`. Actions: `show_sources`, `ask_followup`, `record_source`, `prepare_plan`. Privacy `metadata_only`.
- `business-research`: Prepare source-backed business research briefs with evidence and inference boundaries. Tier `source-gated`. Ladder: `business_question_scoped` -> `source_boundary_recorded` -> `source_quality_recorded` -> `source_evidence_recorded` -> `business_synthesis_recorded` -> `uncertainty_recorded`. Actions: `show_sources`, `ask_followup`, `prepare_strategy_brief`, `show_status`. Privacy `metadata_only`.
- `strategy-synthesis`: Turn goals and evidence into strategy options, tradeoffs, and decision-ready notes. Tier `decision-gated`. Ladder: `decision_scope_recorded` -> `options_recorded` -> `tradeoffs_recorded` -> `recommendation_recorded` -> `decision_status_recorded`. Actions: `show_brief`, `revise_brief`, `record_decision`, `show_status`. Privacy `metadata_only`.
- `meeting-facilitation`: Prepare agendas, discussion prompts, decisions, and record templates. Tier `facilitation-gated`. Ladder: `meeting_goal_scoped` -> `agenda_recorded` -> `discussion_prompts_recorded` -> `decisions_needed_recorded` -> `record_template_ready`. Actions: `show_agenda`, `revise_brief`, `record_decision`, `show_status`. Privacy `metadata_only`.
- `customer-insight-triage`: Cluster customer feedback and choose the next workflow without defaulting to coding. Tier `triage-gated`. Ladder: `feedback_source_scoped` -> `clusters_recorded` -> `severity_opportunity_recorded` -> `next_workflow_recommended`. Actions: `show_triage`, `ask_followup`, `prepare_plan`, `show_status`. Privacy `metadata_only`.
- `ops-review`: Summarize observed operating status, risks, blockers, priorities, and follow-up actions. Tier `status-gated`. Ladder: `review_scope_recorded` -> `status_evidence_recorded` -> `risks_blockers_recorded` -> `priorities_recorded` -> `followups_recorded`. Actions: `show_status`, `record_blocker`, `record_checkpoint`, `prepare_plan`. Privacy `metadata_only`.
- `operating-rhythm`: Maintain meeting, scrum, sprint, retro, decision, and follow-up history with prepared-vs-observed boundaries. Tier `operations-gated`. Ladder: `operation_rhythm_scoped` -> `record_structure_prepared` -> `decisions_actions_recorded` -> `status_boundary_recorded`. Actions: `show_record`, `record_decision`, `record_action`, `export_markdown`, `show_status`. Privacy `metadata_only`.
- `report-package`: Package supplied inputs into reports, executive briefs, and PPT-ready Markdown/JSON outlines. Tier `report-gated`. Ladder: `report_scope_recorded` -> `inputs_organized` -> `package_outline_prepared` -> `approval_boundary_recorded`. Actions: `show_report`, `export_markdown`, `export_json`, `record_approval`, `show_status`. Privacy `metadata_only`.
- `materials-package`: Plan, hand off, and verify material-processing work across decks, PDFs, spreadsheets, documents, HWP, Markdown, and binary exports. Tier `material-gated`. Ladder: `material_scope_recorded` -> `source_inputs_organized` -> `format_qa_ladder_prepared` -> `generation_handoff_prepared_if_needed` -> `export_qa_observed_when_available`. Actions: `show_material_plan`, `choose_target_format`, `prepare_generation_handoff`, `record_export`, `record_qa`, `record_approval`. Privacy `metadata_only`.
- `img-summary`: Prepare source-specific, premium domain-aware, and poster-archetype-aware visual prompt cards for meetings, reports, PRs, issue feedback, research briefings, and release announcements without claiming image generation. Tier `visual-card-gated`. Ladder: `source_kind_selected` -> `visual_format_selected` -> `poster_archetype_selected` -> `card_copy_prepared` -> `prompt_card_prepared` -> `image_generation_capability_checked`. Actions: `show_visual_prompt_card`, `copy_visual_prompt`, `revise_visual_card`, `change_visual_language`, `choose_image_generator`, `setup_image_generator`. Privacy `metadata_only`.
- `scheduled-ops-blueprint`: Prepare recurring Hermes operations as schedule/delivery/silence blueprints without claiming runtime execution. Tier `ops-blueprint-gated`. Ladder: `blueprint_scope_recorded` -> `schedule_policy_prepared` -> `delivery_policy_prepared` -> `silence_policy_prepared` -> `context_chain_prepared` -> `runtime_observed_when_available`. Actions: `show_blueprint`, `revise_schedule`, `confirm_delivery_policy`, `prepare_host_schedule`, `record_observed_runtime`, `show_status`. Privacy `metadata_only`.
- `research-department`: Prepare Scout, Analyst, and Briefer research operations with source inbox and briefing status boundaries. Tier `research-ops-gated`. Ladder: `research_plan_scope_recorded` -> `source_inbox_prepared` -> `briefing_status_prepared` -> `tooling_readiness_prepared` -> `observed_evidence_recorded_when_available`. Actions: `show_research_department_plan`, `revise_research_sources`, `confirm_cadence_delivery_tooling`, `record_source_observation`, `show_status`. Privacy `metadata_only`.
- `reliability-review`: Review incidents, SLOs, error budgets, and remediation follow-ups with strict observed evidence boundaries. Tier `reliability-gated`. Ladder: `reliability_scope_recorded` -> `evidence_boundary_recorded` -> `review_prepared_or_observed` -> `remediation_boundary_recorded`. Actions: `show_evidence`, `record_gap`, `prepare_handoff`, `record_metric`, `show_status`. Privacy `metadata_only`.
- `app-delivery-loop`: Run complete app operation loops from idea through decision, handoff, release, deploy, and monitor status. Tier `delivery-gated`. Ladder: `loop_scope_recorded` -> `decision_gate_recorded` -> `plan_or_release_gate_accepted` -> `handoff_prepared_if_needed` -> `verification_release_gate_recorded` -> `deploy_monitor_observed_when_available`. Actions: `show_delivery_loop`, `accept_plan`, `choose_executor`, `prepare_handoff`, `record_deploy`, `record_monitor_signal`. Privacy `metadata_only`.
- `goal-loop`: Run loopable goal projects through task/project/ambition classification, bounded goal shaping, task discovery, distribution, execution, verification tiers, verifier checks, next-task decisions, runtime ticks with deterministic queue shapes, handoff, feedback, waiting, and resumable status without hidden execution. Tier `loop-gated`. Ladder: `loop_triggered` -> `loopability_assessed` -> `goal_reframed` -> `permission_profile_recorded` -> `runtime_tick_queued` -> `verification_plan_attached`. Actions: `assess_loopability`, `convert_to_loop_goal`, `route_direct_task`, `choose_permission_profile`, `start_loop`, `run_loop_once`. Privacy `metadata_only`.
- `deep-interview`: Clarify intent and boundaries one question at a time before planning or execution. Tier `clarity-gated`. Ladder: `ambiguity_identified` -> `blocking_question_asked` -> `answer_recorded` -> `clarified_brief_ready`. Actions: `answer:clarify`, `cancel`, `rerun_plan`. Privacy `metadata_only`.
- `architect`: Evaluate system boundaries, integration choices, and long-term maintainability. Tier `boundary-gated`. Ladder: `architecture_context_loaded` -> `tradeoffs_recorded` -> `boundary_verdict_recorded`. Actions: `show_review`, `revise_plan`, `approve_plan`. Privacy `metadata_only`.
- `critic`: Challenge plan consistency, quality criteria, and missing verification. Tier `finding-gated`. Ladder: `review_scope_loaded` -> `findings_recorded` -> `verdict_recorded` -> `residual_risk_recorded`. Actions: `show_findings`, `request_changes`, `approve_plan`. Privacy `metadata_only`.
- `qa-specialist`: Design adversarial scenarios and verify user-visible behavior before completion. Tier `scenario-gated`. Ladder: `scenario_matrix_defined` -> `checks_run` -> `pass_fail_recorded` -> `fix_followup_recorded_if_needed`. Actions: `show_status`, `record_check`, `record_blocker`. Privacy `metadata_only`.
- `docs-specialist`: Keep public docs accurate, installable, and aligned with actual behavior. Tier `claim-gated`. Ladder: `claims_scoped` -> `docs_updated` -> `generated_docs_checked` -> `public_claims_verified`. Actions: `show_docs`, `record_claim_check`, `show_status`. Privacy `metadata_only`.
- `github-event-ops`: Route GitHub PR, issue, CI, and review events into triage, review, labeling, or fix-handoff guidance. Tier `event-gated`. Ladder: `event_received` -> `event_classified` -> `route_card_prepared` -> `mutation_observed_when_available`. Actions: `show_event_card`, `prepare_review`, `prepare_label`, `prepare_fix_handoff`, `record_github_observation`. Privacy `metadata_only`.
- `agent-board`: Coordinate multi-Hermes-agent or profile work as board cards with task, handoff, heartbeat, blocker, and completion states. Tier `board-gated`. Ladder: `board_scoped` -> `cards_prepared` -> `heartbeat_recorded_when_available` -> `completion_recorded_when_available`. Actions: `show_board`, `move_card`, `record_heartbeat`, `record_blocker`, `record_completion`. Privacy `metadata_only`.
- `memory-curation-review`: Review stale, conflicting, duplicate, or risky memory and skill guidance with explicit approve/reject/update actions. Tier `curation-gated`. Ladder: `memory_candidates_scoped` -> `conflicts_ranked` -> `review_actions_prepared` -> `approved_write_observed_when_available`. Actions: `show_memory_review`, `approve_update`, `reject_update`, `record_memory_write`, `show_status`. Privacy `metadata_only`.
- `gateway-intent-card`: Normalize gateway session policy for origin, thread, delivery, silent updates, attachments, and status updates. Tier `gateway-gated`. Ladder: `origin_scoped` -> `thread_policy_prepared` -> `delivery_policy_prepared` -> `delivery_observed_when_available`. Actions: `show_gateway_card`, `confirm_delivery`, `record_delivery`, `record_attachment`, `show_status`. Privacy `metadata_only`.
- `executor-runtime-readiness`: Compare executor/runtime options by available tools, missing tools, credentials, authority, and handoff mode. Tier `runtime-readiness-gated`. Ladder: `task_runtime_scoped` -> `tool_matrix_prepared` -> `handoff_mode_selected` -> `runtime_dispatch_observed_when_available`. Actions: `show_runtime_matrix`, `choose_executor`, `prepare_handoff`, `record_dispatch`, `show_status`. Privacy `metadata_only`.
- `deliverable-package`: Track file deliverables through prepared, generated, QA, approved, attached, and delivered states. Tier `deliverable-gated`. Ladder: `deliverable_scoped` -> `format_plan_prepared` -> `generation_handoff_prepared` -> `file_observed_when_available` -> `attachment_observed_when_available`. Actions: `show_deliverable_card`, `choose_format`, `prepare_generation_handoff`, `record_file`, `record_attachment`. Privacy `metadata_only`.
- `voice-operator`: Convert terse voice/mobile requests into safe clarify, plan, status, handoff, or confirmation actions. Tier `accessibility-gated`. Ladder: `voice_request_received` -> `ambiguity_checked` -> `safe_action_prepared` -> `confirmation_observed_when_required`. Actions: `ask_clarification`, `confirm_action`, `show_status`, `prepare_handoff`. Privacy `metadata_only`.
- `toolbelt-readiness`: Check required MCP servers, CLIs, APIs, credentials, connectors, and local tools for a workflow. Tier `tool-readiness-gated`. Ladder: `workflow_tools_scoped` -> `tool_requirements_listed` -> `installed_state_recorded_when_available` -> `credential_gaps_recorded`. Actions: `show_toolbelt`, `open_setup`, `record_tool_check`, `prepare_handoff`, `show_status`. Privacy `metadata_only`.
- `ops-observability-card`: Report wrapper-safe token, cost, latency, run history, queue, and failure-mode telemetry boundaries. Tier `observability-gated`. Ladder: `telemetry_scope_recorded` -> `local_metrics_summarized` -> `failure_modes_checked` -> `provider_truth_observed_when_available`. Actions: `show_observability`, `record_metric`, `record_failure_mode`, `show_status`. Privacy `metadata_only`.
- `agent-ops-review`: Prepare a manager-facing quality and throughput review for AI-agent research, coding, review, and status work. Tier `manager-review-gated`. Ladder: `manager_scope_recorded` -> `quality_lanes_prepared` -> `evidence_gaps_named` -> `next_action_selected` -> `runtime_observation_recorded_when_available`. Actions: `show_agent_ops_review`, `choose_ops_lane`, `prepare_research_lane`, `prepare_coding_lane`, `prepare_review_lane`, `refresh_agent_ops_status`. Privacy `metadata_only`.
- `workflow-learning`: Record workflow attempts as metadata-only learning traces, deterministic evals, missed-route review bundles, review-only improvement candidates, non-applying patch proposals, regression cases, readiness audits, a repairable learning index, and redacted review exports. Tier `learning-gated`. Ladder: `trace_recorded` -> `eval_recorded` -> `improvement_candidate_reviewed` -> `regression_case_recorded` -> `learning_readiness_audited` -> `learning_index_checked`. Actions: `record_workflow_learning_trace`, `record_missed_route`, `show_learning_review_queue`, `show_learning_eval`, `propose_skill_improvement`, `review_improvement`, `approve_improvement`, `revise_improvement`, `reject_improvement`, `prepare_patch_proposal`, `show_patch_proposal`, `copy_patch_handoff`. Privacy `metadata_only`.

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

Record only what is observed. A Codex-selected `coding_delegation.json` record and its `prepared_coding_delegation` run envelope prove a prepared handoff, not execution. Executor-choice, prompt-only, and runtime handoffs do not create lifecycle runtime runs. If Hermes or a chosen oh-my runtime does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.
