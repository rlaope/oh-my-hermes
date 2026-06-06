# Chat Wrapper Examples

This page shows how a Discord-style wrapper can render OMH output as a normal
Hermes Agent chat response. The example is generated from local fixtures; it
does not require a bot SDK, credentials, network access, an LLM call, or Hermes
core changes.

## Commands Used

```sh
uv run python examples/discord-adapter-shim.py
uv run python -m src.cli demo orchestration
```

The first command renders the fixture event in
`examples/wrapper-events/discord-safe-feature.json`. The second command renders
the full deterministic path:

```text
recommend -> chat response -> Hermes plan -> Codex handoff -> status card
```

## Discord-Style Plan Response

```text
# repo-planning

maintainer-1
I want to safely add a feature to this repo

Hermes Agent  BOT
I routed this to `plan` because it needs a safe plan first.

Accept or revise the plan first; the handoff button stays disabled until
acceptance. A draft plan is still only planning evidence.

[ Accept plan ] [ Revise plan ] [ Prepare handoff ] disabled

State
- Phase: planning
- Next action: present_plan
- Claim boundary: A draft plan is not execution evidence.
```

User-facing effect:

- The user does not need to know an `omh` command.
- Hermes Agent explains why the request became a plan-first workflow.
- The wrapper can show `Accept plan` and `Revise plan` immediately.
- `Prepare handoff` is visible but disabled until the plan is accepted.
- The response names what is not evidence yet instead of sounding like coding
  already happened.

## Discord-Style Handoff Status Card

After the wrapper prepares the handoff, the demo status card can be rendered as
a progress block in the same thread:

```text
Hermes Agent  BOT
A Codex handoff is ready.

I have prepared the handoff, but executor dispatch is not observed yet.

Status
[ready]   Handoff
[pending] Execution
[pending] Verification
[n/a]     Review
[pending] CI
[pending] Merge Ready
[pending] Merged

Primary action: Send to Codex
Claim boundary: Preparation is not execution evidence.
```

User-facing effect:

- Prepared handoff is presented as ready to dispatch, not completed work.
- Execution, verification, CI, merge-readiness, and merge stay separate.
- The wrapper can keep editing the same thread as evidence arrives.

## JSON-to-UI Mapping

| Rendered UI | Source field |
| --- | --- |
| Bot headline | `chat_response.headline` |
| Bot body | `chat_response.body` |
| Button ids | `chat_response.actions[].id` |
| Thread key | `thread_key` |
| Current phase | `chat_response.state.phase` |
| Evidence boundary | `chat_response.claim_boundary` |
| Status headline | `status_card.headline` |
| Status rows | `status_card.steps[]` |
| Primary status action | `status_card.primary_action` |

Wrappers should render these fields natively and keep platform-specific work
outside OMH: authentication, posting, message edits, retries, buttons, and
thread lifecycle all remain adapter responsibilities.
