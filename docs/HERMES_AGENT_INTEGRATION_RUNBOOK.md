# Hermes Agent Integration Runbook

This is an operator reference, not an `omh` command.

Use this runbook when you operate a Hermes-agent wrapper that receives natural
language from Discord, Slack, or another hosted chat surface and renders OMH's
local deterministic contracts as native chat UX.

The chat user should not need to know command names. The wrapper can use OMH
commands internally, but user-facing replies should talk in terms of plans,
clarifications, handoffs, status cards, blockers, and observed evidence.

## Audience

This document is for wrapper and agent operators who need to answer three
questions:

- Which local OMH contract should the Hermes-agent wrapper consume?
- Which owner is responsible for each stage?
- Which status claims are backed by observed evidence, and which are not?

## Upstream Basis

OMH's model of upstream Hermes Agent (`omh hermes readiness`,
`omh hermes retained-context`) is refreshed against a manually checked basis,
not a live network probe. Current basis: Hermes Agent v0.19.0 "Quicksilver"
(released 2026-07-20), checked 2026-07-21. Upstream ships majors on roughly a
2-week cadence, so treat this basis as a snapshot and re-check
`src/workflows/hermes_readiness_catalog.py` `official_basis()` periodically.

Concrete deltas an operator or wrapper should account for at this basis:

- **Smart approvals (LLM-based command review) are now the default** in
  v0.19.0. A wrapper or operator that assumed a plain prompt-per-command
  approval flow should model LLM-reviewed command approval instead;
  `approvals.deny` globs still hard-block regardless of smart-approval state.
- **`delegate_task` background subagents and the Kanban board are
  upstream-native multi-agent primitives.** `delegate_task` calls are
  background-by-default with handles and live `tail -f` transcripts; the
  Kanban board (`kanban.db`, `kanban_*` toolset) is a durable, multi-profile
  work queue with orchestrator auto-decomposition, swarm topology,
  worktree-per-task, and per-task model overrides. OMH should prepare
  handoffs onto these surfaces rather than reimplement a competing work
  queue or subagent scheduler.
- **Desktop Projects and the Kanban board manage git worktrees natively.**
  OMH's own worktree isolation guidance (see
  [Orchestration Patterns](ORCHESTRATION_PATTERNS.md) and
  [Multi-Agent Operations](MULTI_AGENT_OPERATIONS.md)) is prepared guidance
  only; it can collide with worktrees Hermes itself is already managing for
  the same task, so treat "a worktree should exist here" as advisory, not a
  claim that OMH owns worktree lifecycle.
- **`/goal` completion contracts (evidence-based done)** are upstream's own
  analogue of OMH's verification/evidence loops. Prefer aligning OMH
  verification narration with `/goal` semantics rather than inventing a
  parallel completion vocabulary.
- **Session export formats** (Markdown, Quarto, HTML, prompt-only, and
  Hugging-Face-ready trace) are the stable transcript-extraction surface as
  of v0.19.0; prefer them over scraping `~/.hermes/sessions/` directly.

This section is executor-neutral: the same guidance applies whether the
coding executor behind a handoff is Codex, Claude Code, Hermes's own runtime,
or another selected executor.

## Product Boundary

| Owner | Owns | Does not own |
| --- | --- | --- |
| Hermes Agent | Chat continuity, clarification, research, planning, status narration, and user-visible actions. | Hidden coding execution, or CI/merge proof. |
| OMH | Deterministic local routing, playbook, planning, handoff, session, status, and fixture contracts. | Hermes core patches, hidden LLM calls, or executor launch. |
| Selected coding executor | Main implementation work, verification output, review fixes, and execution evidence after dispatch or prompt handoff. | Chat UX or OMH contract generation. |
| Runtime artifacts | Metadata-only observed evidence for dispatch, result, verification, review, CI, merge readiness, and merge. | Raw chat secrets or unobserved assumptions. |

## Contract Surfaces

The wrapper normally starts with `chat_interaction/v1`. If the OMH plugin is
available, use `omh_interact` so Hermes can receive the same envelope and record
a metadata-only wrapper session without asking for shell approval.

```sh
omh chat interact --source discord --event-json event.json
```

The returned envelope is safe for a wrapper to render without parsing prose:

- `thread_key`: stable wrapper thread identity.
- `mode`: `clarify`, `plan`, `delegate`, `route`, or `status`.
- `next_action`: the next operator or wrapper action.
- `chat_response`: renderable response text, action ids, state, and claim
  boundary.
- `overclaim_guard`: invariant status rules the wrapper should preserve.
- `target_notice`: optional concise notice when the observed Hermes target
  topology changed from one target to many or many to one.
- `target_topology`: optional `omh_target_topology/v1` summary with
  `active_agent_count`, `current_target_id`, and `requires_skill_scope_awareness`.
- `plan`, `delegation`, or `status`: optional machine-readable payload for the
  selected mode.

Use `chat_response/v1` for the visible reply. Use `status_card/v1` when a linked
runtime run exists and the wrapper needs a compact progress card.

## Operator Flow

1. Receive the platform event and store only the metadata needed by the wrapper.
2. Ask OMH for a platform-neutral interaction envelope.
3. Render `chat_response.headline`, `chat_response.body`,
   `chat_response.actions`, and `chat_response.claim_boundary` on rich or web
   surfaces that can handle the original Markdown body. The headline already
   includes the visible OMH usage marker, such as `[omh] web-research`; use
   `chat_response.plain_headline` only when a compact surface needs the
   unprefixed text.
4. Apply `chat_response.messenger_rendering` according to the target surface's
   `render_profile`. Discord, Slack, and Telegram default to
   `limited_markdown`; Hermes TUI, web, and generic rich Markdown surfaces
   default to `rich_markdown`. Render
   `chat_response.messenger_rendering.body_text` for the selected profile. Use
   `fallback_body_text` when relaying a rich response into a narrower chat
   surface, or pass `--render-profile limited_markdown` when calling
  plugin `omh_interact` or `omh chat interact`. Render the prefix once per response, not on every
   paragraph; repeat it only when the adapter posts a long response as separate
   message chunks.
5. If `target_notice.action` is `ask_to_apply_target_change`, render a short
   setup-change comment and an apply action. Until accepted or auto-applied,
   keep the workflow scoped to the current thread target. The
   `apply_target_change` action payload carries
   `target_observation.source_metadata`; pass that sanitized metadata back to
   the wrapper backend with target-change apply enabled to persist the same
   target update.
6. If the response is a plan, wait for the user to accept or revise the plan
   before preparing a handoff.
7. If a coding handoff is prepared, check `executor_readiness/v1` before first
   dispatch for the selected profile. A wrapper may run
   `omh coding executor-readiness --executor <profile>` once, cache the result,
   and skip later probes unless the user forces a retry. If readiness is
   `missing` or `blocked`, ask the user to choose another coding agent,
   configure PATH, continue in Hermes, or keep a prompt/runtime handoff.
8. If the selected profile is Hermes, render `hermes_coding_harness/v1` from
   the prepared runtime handoff or wrapper-session status. It is a read-only
   projection, so answer status questions with the current stage, lane owner,
   next action, and missing evidence. Do not say Hermes created a PR, passed
   review, passed CI, or reached merge readiness unless the matching
   `runtime_observation/v1` event exists.
9. Dispatch the `coding_executor_handoff/v1`
   payload to the external executor outside OMH. For Codex targets, use
   `codex_skill` and `codex_invocation.dispatch_text_template`; this is the
   `$skill {message}` surface Codex actually receives.
10. Record only evidence the wrapper actually observed: dispatch, executor
   result, verification, review, CI, merge readiness, and merge.
11. Re-render status from OMH after each observed transition.

## State Transition Reference

| Scenario | From | To | Wrapper action | Evidence boundary |
| --- | --- | --- | --- | --- |
| Clarification needed | `message_received` | `clarifying` | Ask one blocking question. | No plan or execution is approved. |
| Plan presented | `message_received` | `planning` | Show accept/revise actions. | A draft plan is not execution evidence. |
| Target topology changed | `single_agent_target` or `multi_agent_targets` | pending target update | Show `apply_target_change` or auto-apply only when the wrapper is configured to do so. | Setup topology is not proof another Hermes agent observed the workflow. |
| Handoff prepared | `plan_accepted` | `handoff_prepared` | Show send-to-executor action. | Prepared handoff is not execution evidence. |
| Hermes harness prepared | `runtime_handoff_prepared` | `hermes_coding_harness/v1` | Show current stage, lane owner, next action, and missing evidence. | Harness projection is not worker start, verification, review, CI, PR, or merge evidence. |
| Dispatched, waiting | `handoff_prepared` | `dispatched` | Wait for executor evidence. | Dispatch is not completion evidence. |
| Review pending | `executor_completed` | `awaiting_review` | Show review-pending status. | Execution is observed; review is not. |
| CI pending | `review_passed` | `awaiting_ci` | Show CI-pending status. | Review is not CI evidence. |
| CI failed | `ci_started` | `blocked` | Surface the failing checks. | Failed CI is not merge-ready. |
| Merge ready | `ci_passed` | `merge_ready` | Show merge-ready status. | Ready to merge is not the same as merged. |
| Merged | `merge_ready` | `merged` | Show merged status. | Merged requires observed merge evidence. |

The golden fixture at `examples/wrapper-golden/hermes-agent-integration.json`
maps these transitions back to the status ladder scenarios in
`examples/wrapper-golden/status-ladder.json`.

## Evidence Rules

- A route decision is not execution evidence.
- A draft plan is not execution evidence.
- A prepared handoff is not executor/runtime dispatch, worker start, or worktree creation.
- Executor dispatch is not executor completion.
- Executor completion is not review evidence.
- Review evidence is not CI evidence.
- CI passing is not merge evidence.
- Merge readiness is not merge evidence.
- Missing or contradictory evidence should produce a blocker/status update, not
  a completion claim.

## Recovery And Troubleshooting

Use wrapper sessions when the platform process can restart between user actions:

```sh
omh chat session start --source discord --source-event-id "$MESSAGE_ID" --channel-ref "$CHANNEL_ID" "risky refactor"
omh chat session accept-plan "$SESSION_ID"
omh chat session prepare-handoff "$SESSION_ID" "risky refactor"
omh chat session status "$SESSION_ID"
```

Before a handoff is prepared, the status card should explain the plan or
executor-choice state without showing executor start/result buttons. After a
handoff is prepared, render the returned `chat_response.actions` as
Hermes-native actions. A normal user should see actions such as Start Codex
session, Start Claude Code session, Attach coding session, Refresh status,
Record completed, Record blocked, or Ask Hermes to verify. The wrapper process
maps those actions back to backend calls; the user does not need to know the
command names.

Start-session buttons include `executor_launch/v1` under
`executor_actions[].payload.launch`. The payload names the configured executor
profile so Hermes can start the right path: Codex if setup/session selected
Codex, Claude Code if it selected Claude Code, Hermes/runtime paths when those
profiles are selected. For compatibility, `executor_launch/v1` keeps
`ui_only`, `not_backend_execution`, and `execution_policy` conservative; wrappers
should read `terminal_launch_available` and `session_start_capability` before
showing a terminal start command. Codex command templates use `codex` and
optional `codex --cd`; Claude Code command templates use `claude` and optional
`claude --add-dir`. Prompt placeholders use `{executor_prompt_shell_quoted}`,
and workspace command templates use `{workspace_path_shell_quoted}` for
shell-safe paths. OMH itself still does not execute the coding agent; Hermes or
the wrapper starts or attaches the terminal/app session, then calls
`open-executor --observed` only after that coding session exists.

For a Hermes-owned coding handoff, the wrapper does not need to invent a custom
status model. Read `hermes_coding_harness/v1` and render the prepared graph:

- current workflow stage: intake, scope, plan, workspace, build, verify,
  review, docs sync, PR preparation, or handover
- lane state: builder, verifier, reviewer, docs, and PR
- nested `verification_matrix`, `docs_sync`, and `pr_preparation` sections
- missing `runtime_observation/v1` events before any stronger claim is allowed

This lets Hermes answer “what are you doing now?” with a concrete stage report,
while preserving the rule that prepared PR packages are not GitHub PR creation.

For a Codex handoff, the wrapper can record an observed open and later result:

```sh
omh chat codex-progress --jsonl "$CODEX_JSONL" --evidence-ref codex-jsonl
omh chat session open-executor "$SESSION_ID" --observed \
  --external-session-ref "$CODEX_THREAD" \
  --codex-session-ref "$CODEX_SESSION" \
  --codex-thread-ref "$CODEX_THREAD" \
  --codex-log-jsonl "$CODEX_JSONL" \
  --codex-log-ref codex-jsonl
omh chat session record-executor "$SESSION_ID" --result completed \
  --evidence-ref codex-summary \
  --codex-log-jsonl "$CODEX_JSONL" \
  --codex-log-ref codex-final-jsonl
omh chat session request-verification "$SESSION_ID"
omh chat session status "$SESSION_ID"
```

For live Codex progress while the process is still running, bind the runtime run
or wrapper session once, then call the stateful observer every time the wrapper
has a new JSONL/process-output snapshot:

```sh
omh runtime progress bind --run "$RUN_ID" \
  --executor-profile codex \
  --process-session-id "$CODEX_PROCESS_SESSION" \
  --codex-session-ref "$CODEX_SESSION" \
  --evidence-ref codex-jsonl

omh runtime progress observe --run "$RUN_ID" \
  --codex-log-jsonl "$CODEX_JSONL" \
  --process-status running \
  --evidence-ref codex-jsonl

omh runtime progress status
```

`runtime progress observe` returns `reported=true`, `reporting_action=send_report`,
and `chat_report` only when a meaningful transition is observed, such as
`executor_dispatched`, `repo_exploration`, `diff_started`, `tests_started`,
`tests_failed`, `tests_passed`, `executor_completed`, `executor_failed`, or
`executor_blocked`. Repeating the same snapshot returns `reported=false`,
`reporting_action=suppress`, and a `suppressed_reason` such as
`duplicate_transition` or `repeat_interval`; wrappers should not send a chat
message for those no-op results. The persisted binding stores compact state,
safe counters, and artifact hashes so repeated observe calls do not spam the
thread. It does not store raw logs or hidden reasoning. The older
`runtime progress-bind`, `runtime progress-observe`, and `runtime progress-status`
forms remain compatibility aliases.

`omh chat codex-progress` is an adapter helper for the raw-output gap: hosted
wrappers can pipe Codex JSONL or process output into it and render the compact
`chat_summary` instead of dumping event streams into chat. The output is an
observable event summary, not think-log access; it must not expose hidden
reasoning, raw JSON events, or unobserved review/CI/merge claims. If an
explicit JSONL path cannot be read, the adapter must surface that as missing
evidence instead of treating it as an empty observed log.

Large output belongs in the wrapper or operator artifact store, not in Hermes
chat context. `codex_progress_summary/v1` includes
`raw_output_artifact` (`omh_context_artifact_ref/v1`), `context_budget`, capped
evidence refs, and a bounded human-readable summary so wrappers can reference
the raw log without copying it into the prompt. The artifact reference is
prepared context only; it is not execution, review, CI, merge-readiness, or
merge evidence.

Long executor, goal, research, and workflow runs should report meaningful
events instead of relying on 3-5 minute polling. Use `omh_progress_event/v1` for
state changes such as failure discovered, root cause identified, fix strategy
selected, files or area chosen, targeted tests pass/fail, full tests
start/pass/fail, commit created, PR created/updated, or blocker encountered.
Each event should be one or two human-readable sentences with optional file
refs, compact artifact refs, severity/status, and the standard claim boundary.
Raw logs, JSONL, command output, and transcripts stay in artifacts referenced by
the event; the event itself is progress context, not execution/review/CI/merge
evidence.

When Codex performs a review, wrappers can expose a human-readable review
context summary without raw logs:

```sh
omh chat codex-review \
  --codex-session-ref "$CODEX_SESSION" \
  --codex-thread-ref "$CODEX_THREAD" \
  --codex-log-jsonl "$CODEX_JSONL" \
  --codex-log-ref codex-jsonl \
  --evidence-ref codex-review-summary \
  --codex-review-status changes_requested \
  --codex-review-summary "$HUMAN_READABLE_CODEX_REVIEW_SUMMARY" \
  --codex-review-finding-count 2
```

`codex_review_summary/v1` is review-context metadata for Hermes narration. It
separates the observed Codex-reviewed result from Hermes' own summary text,
does not expose raw JSONL or hidden reasoning, and does not claim CI,
merge-readiness, merge, or review-fix evidence. If the review requests fixes
and an explicit `codex_session_ref` was observed, the handback contract includes
a copyable `codex exec resume <session_id>` template for the wrapper/operator.
OMH core still does not launch Codex or claim that fixes were applied.

When a follow-up prompt arrives while Codex is still active, wrappers can combine
the latest observed progress with a safe handling recommendation:

```sh
omh chat codex-followup "$FOLLOW_UP" \
  --session-id "$SESSION_ID" \
  --codex-log-jsonl "$CODEX_JSONL" \
  --codex-log-ref codex-jsonl \
  --codex-review-status changes_requested \
  --codex-review-summary "$HUMAN_READABLE_CODEX_REVIEW_SUMMARY"
```

The follow-up contract returns a prompt hash/length, the latest observable Codex
activity summary, and a recommendation to append to the observed Codex session
only when a same-goal wrapper session or explicit same-goal assertion is present.
Otherwise it recommends clarifying or routing a new task. It does not append the
prompt, launch Codex, expose raw logs, or claim review/CI/merge evidence. When a
review summary is provided, it is carried as compact review context for the
resumed Codex session; it is not a hidden think log and not proof that review
fixes have already happened.

When `codex_session_ref` is observed, status includes a resume-capable launch
contract such as `codex exec resume <session_id>`. A generic
`external_session_ref` or thread reference is shown as observed context only; it
does not produce a resume command by itself. Resume remains a wrapper or
operator action. OMH records the reference and summary metadata only; it does
not launch Codex, and it does not claim resumed work until the wrapper records
observed session/result evidence.

The resulting display status lines are intended for normal chat surfaces:

```text
Coding agent is running in Codex.
Executor session is attached.
Handoff is ready.
Dispatch/open has been observed.
Executor result has not been observed yet.
Hermes verification has not been requested yet.
Observed Codex metadata: session codex-session-1, thread codex-thread-1; event summaries=4.
Codex observable activity summary: Codex is inspecting files/tests. Codex changed files. Status: activity_observed.
```

When the user asks “what is happening with that coding task?”, prefer the
`coding_briefing/v1` object from `omh chat session status`. Render
`coding_briefing.user_facing_lines[]` for a readable answer, and use
`coding_briefing.progress[]`, `pending_gaps[]`, and `evidence_summary` for
expanded status. Keep `status_card/v1` compact; do not treat the briefing as
proof of execution, verification, review, CI, or merge unless the matching
observed evidence appears in the briefing.

For prompt-only Claude Code or generic agents, the same wrapper session action
records attached/result metadata without creating a Codex lifecycle run. For
Hermes/OMX/OMO/OMC runtime handoffs, an observed open also records the
`runtime_start` ladder step; worktree, worker, review, CI, and merge still
require separate evidence.

If a wrapper cannot prove a transition, keep the status at `not_observed` and
show the next required evidence instead of inferring progress.

## Release Check

Before depending on the wrapper contract in a release candidate, run:

```sh
PYTHONPATH=tests uv run python -m unittest tests/test_wrapper_contract.py -v
PYTHONPATH=tests uv run python -m unittest tests/test_wrapper_golden_examples.py -v
uv run python -m omh.cli harness validate
git diff --check
```
