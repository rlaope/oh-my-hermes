# Voice Operator

Load this on-demand contract after the compact `voice-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- The speech is material to transcribe or summarize; use `omh-media-input`.

## Examples

Good example:

- Prompt: voice-operator 'release before lunch, check risky parts' from mobile.
- Expected behavior: Produce `prepare_voice_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: voice-operator assume the user approved a destructive action from a vague voice note.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- voice-operator/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- voice-operator/v1 metadata-only runtime or wrapper card when recorded
