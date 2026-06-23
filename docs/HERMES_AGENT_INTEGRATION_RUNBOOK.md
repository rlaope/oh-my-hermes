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
8. Dispatch the `coding_executor_handoff/v1`
   payload to the external executor outside OMH. For Codex targets, use
   `codex_skill` and `codex_invocation.dispatch_text_template`; this is the
   `$skill {message}` surface Codex actually receives.
9. Record only evidence the wrapper actually observed: dispatch, executor
   result, verification, review, CI, merge readiness, and merge.
10. Re-render status from OMH after each observed transition.

## State Transition Reference

| Scenario | From | To | Wrapper action | Evidence boundary |
| --- | --- | --- | --- | --- |
| Clarification needed | `message_received` | `clarifying` | Ask one blocking question. | No plan or execution is approved. |
| Plan presented | `message_received` | `planning` | Show accept/revise actions. | A draft plan is not execution evidence. |
| Target topology changed | `single_agent_target` or `multi_agent_targets` | pending target update | Show `apply_target_change` or auto-apply only when the wrapper is configured to do so. | Setup topology is not proof another Hermes agent observed the workflow. |
| Handoff prepared | `plan_accepted` | `handoff_prepared` | Show send-to-executor action. | Prepared handoff is not execution evidence. |
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

`omh chat codex-progress` is an adapter helper for the raw-output gap: hosted
wrappers can pipe Codex JSONL or process output into it and render the compact
`chat_summary` instead of dumping event streams into chat. The output is an
observable event summary, not think-log access; it must not expose hidden
reasoning, raw JSON events, or unobserved review/CI/merge claims.

When `codex_session_ref` is observed, status includes a resume-capable launch
contract such as `codex exec resume <session_id>`. That is still a wrapper or
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
uv run python -m src.cli harness validate
git diff --check
```
