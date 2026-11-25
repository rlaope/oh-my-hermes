# Media Input Operator

Load this on-demand contract after the compact `media-input-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- The audio is an instruction to carry out; use `omh-voice-input`.

## Examples

Good example:

- Prompt: media-input-operator transcribe this audio meeting and summarize action items with evidence and timestamp boundaries.
- Expected behavior: Produce `prepare_media_input_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: media-input-operator invent a YouTube transcript and claim the timestamps are verified without media evidence.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- media_input_task_card/v1
- media_source_scope/v1
- transcript_boundary/v1
- media_summary_plan/v1
- media_result_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- media_input_task_card/v1 metadata-only wrapper card when prepared
- media_source_scope/v1 with media type, source location, permission boundary, requested time range, and stop condition
- transcript_boundary/v1 separating supplied transcript, missing transcript, ASR/extraction requirement, language, speaker labels, and confidence gaps
- media_summary_plan/v1 naming action-item, timestamped, clip, chapter, quote, or evidence-linked summary method
- media_result_manifest/v1 only when supplied transcript, media file metadata, provider response, or observed transcript output exists
