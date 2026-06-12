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

The wrapper normally starts with `chat_interaction/v1`.

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
   `chat_response.actions`, and `chat_response.claim_boundary`.
4. If `target_notice.action` is `ask_to_apply_target_change`, render a short
   setup-change comment and an apply action. Until accepted or auto-applied,
   keep the workflow scoped to the current thread target. The
   `apply_target_change` action payload carries
   `target_observation.source_metadata`; pass that sanitized metadata back to
   the wrapper backend with target-change apply enabled to persist the same
   target update.
5. If the response is a plan, wait for the user to accept or revise the plan
   before preparing a handoff.
6. If a coding handoff is prepared, dispatch the `coding_executor_handoff/v1`
   payload to the external executor outside OMH. For Codex targets, use
   `codex_skill` and `codex_invocation.dispatch_text_template`; this is the
   `$skill {message}` surface Codex actually receives.
7. Record only evidence the wrapper actually observed: dispatch, executor
   result, verification, review, CI, merge readiness, and merge.
8. Re-render status from OMH after each observed transition.

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

Use coding lifecycle commands only after a linked handoff run exists:

```sh
omh coding lifecycle dispatch --run "$RUN_ID"
omh coding lifecycle result --run "$RUN_ID" --result completed --evidence-ref codex-log
omh coding lifecycle verify --run "$RUN_ID" --completion-status completed
omh coding lifecycle report --run "$RUN_ID"
```

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
