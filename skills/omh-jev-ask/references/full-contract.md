# Jev Ask

Load this on-demand contract after the compact `jev-ask` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`jev-ask` exists so a typed judgment about supplied text comes back as numbers the user can threshold, instead of a paragraph from a generative model, with one explicit call the user asked for.

## Do Not Use When

- The user wants a generative second opinion from Claude, Gemini, or another advisor; use `omh-ask`.
- The user is choosing between strategic options and wants tradeoffs and a recommendation; use `omh-decide`.
- The user wants Jev as a chat or coding model; that is a model setting, and Jev writes no text; use `omh-model-setup`.
- The user is writing application code that calls TypeSafe; point at the vendor's own SDK documentation rather than calling the tool.

## Examples

Good example:

- Prompt: ask jev whether this README section covers installation
- Expected behavior: Say the section text leaves the machine, send one Noul with the section as `state`, and report the probability, served model, and cost.
- Why: One atomic yes/no question over supplied text is what a typed ask answers.

Bad example:

- Prompt: ask jev to write a better README
- Expected behavior: Explain that Jev returns probabilities and writes no text; offer a typed question instead or continue as main_model.
- Why: Generation is outside what the tool can return.

## Completion Checklist

- The user asked for Jev in this turn and was told what `state` carries.
- The reported numbers match the tool result, with the served model and cost source.
- A non-answer was reported as its status, not as an answer.

## Recovery Notes

- If `omh_jev_ask` is not in the tool list, say Jev is unavailable, point at the `plugin_jev_sidekick` line of `omh doctor`, and continue as main_model through the partner workflow.
- If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.
- If the tool refuses `credential_like_content`, remove the secret-looking text from `state` rather than redacting it silently, and tell the user what was removed.

## When to Use

Use when the user asks Jev a typed question about supplied text -- whether it does something, which of named options fits, or how it rates on an ordered scale -- or wants help writing such questions.

Routing signals: `jev-ask`, `ask jev`, `jev question`, `jev score`

## Workflow Contract

Category: `gateway`
Phase: `jev-ask`
Hermes role: `guide`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Each question is atomic, self-contained, and independent of the others; a Choice carries an `unknown` option.
- `state` holds only the evidence the questions need.
- The report quotes numbers verbatim with the served model, attempts, and cost source.

Handoff policy:

Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; the partner workflow keeps its own verdict and Jev's answers are one more input to it.

Required inputs:

- the text to judge
- one or more independent questions

Expected outputs:

- Jev's probabilities per question
- served model, attempts, and cost
- the non-answer status when there is no answer

Artifact expectations:

- one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text

Safety rules:

- Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.
- Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.
- A non-answer status is never an answer: report it and continue without Jev.
- Never ask Jev what code can compute: counts, dates, arithmetic, or string checks.
- Report a probability between 0.4 and 0.6 as uncertain, never as yes or no.
