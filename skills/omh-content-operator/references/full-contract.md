# Content Operator

Load this on-demand contract after the compact `content-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- The user wants a draft to stop sounding machine-written - strip AI tells or match their own voice - with no audience, source, or review gate to scope; load Hermes' bundled `humanizer` skill instead of this one.

## Examples

Good example:

- Prompt: content-operator write customer release notes for 4.2 from the attached changelog; legal reviews them first.
- Expected behavior: Produce `prepare_content_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: content-operator send the 4.2 announcement to the customer list.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- content_task_card/v1
- source_scope/v1
- audience_tone_style/v1
- content_review_gate/v1
- content_output_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- content_task_card/v1 metadata-only wrapper card when prepared
- source_scope/v1 with supplied sources, missing sources, fact-risk, citation need, and no-invention rule
- audience_tone_style/v1 with audience, channel, language, tone, style guide, length, format, and accessibility constraints
- content_review_gate/v1 separating draft, reviewer approval, legal/compliance needs, publish/send/file-export authority, and stop condition
- content_output_manifest/v1 only when produced draft, revision diff, approval, export, publish, or delivery evidence is observed
