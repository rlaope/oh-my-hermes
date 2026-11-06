# Jev Route

Load this on-demand contract after the compact `jev-route` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`jev-route` exists so an undecidable route can get a typed answer from Jev that OMH observed itself and can score later, without letting that answer re-route anything.

## Do Not Use When

- The route was already decided; there is no route question to answer.
- The user is choosing a model or provider rather than a workflow; use `omh-model-setup`.
- The host model is recording its own pick; recording a main_model answer needs no ask.

## Examples

Good example:

- Prompt: ask jev which workflow fits this request
- Expected behavior: Send the route_question block with the message as `state`, show Jev's ranked pick as a question to the user, and record it with the ask_id.
- Why: The route was undecidable and the user asked Jev to pick.

Bad example:

- Prompt: use jev as my router model
- Expected behavior: Route to model setup: this is a configuration request, and Jev cannot be a chat model.
- Why: Choosing a model is not answering a route question.

## Completion Checklist

- The block was sent unchanged and its digest matches the recorded answer.
- No workflow was dispatched on Jev's answer alone.

## Recovery Notes

- If `omh_jev_ask` is not in the tool list, say Jev is unavailable, point at the `plugin_jev_sidekick` line of `omh doctor`, and continue as main_model through the partner workflow.
- If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.
- If the tool refuses `credential_like_content`, remove the secret-looking text from `state` rather than redacting it silently, and tell the user what was removed.

## When to Use

Use when an OMH route came back undecidable with a `route_question` block, the answerer ladder lists `omh_jev_ask`, and the user asks Jev to pick the workflow.

Routing signals: `jev-route`, `ask jev which workflow`, `jev pick the workflow`

## Workflow Contract

Category: `gateway`
Phase: `jev-route`
Hermes role: `guide`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- `state` is the user's message, and the user was told it leaves the machine.
- The answer is recorded with the `ask_id` the tool returned.
- `none` winning is reported as no workflow fitting, not as an error.

Handoff policy:

Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; the partner workflow keeps its own verdict and Jev's answers are one more input to it.

Required inputs:

- the `route_question` block
- the user's message

Expected outputs:

- Jev's Choice and fit probabilities
- an `omh_route_answer` record with `answered_by: omh_jev_ask`
- a clarification offered to the user

Artifact expectations:

- one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text

Safety rules:

- Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.
- Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.
- A non-answer status is never an answer: report it and continue without Jev.
- The deterministic route stays in force: present Jev's pick as a clarification and dispatch nothing without the user.
- Pass the block unchanged; editing a question changes its digest and breaks the record join.
