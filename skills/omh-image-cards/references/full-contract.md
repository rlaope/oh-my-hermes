# Img Summary

Load this on-demand contract after the compact `img-summary` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs a deck, PDF, spreadsheet, HWP, Markdown package, or binary file export plan; use `omh-materials-package`.
- The user wants a text-only report, leadership brief, or PPT-ready outline; use `omh-report-package`.
- The user asks OMH to directly generate, inspect, upload, or post an image without a wrapper-supplied observed evidence path.
- A standalone picture with no source material to summarize; call the host image tool with the user's own prompt, no card format.
- The user wants a general-purpose stylized infographic generated directly from a layout-by-style preset rather than an OMH evidence-bounded PR/meeting card brief; load Hermes' bundled `baoyu-infographic` skill instead of this one.

## Examples

Good example:

- Prompt: img-summary make a PR summary card for reviewers.
- Expected behavior: Prepare visual_prompt_card/v1 with the PR review infographic format, copy mode, generation prompt, negative prompt, and not-evidence boundaries.
- Why: The request asks for an image-card communication artifact, not a PDF/deck package or hidden image generation.

Bad example:

- Prompt: img-summary prove this generated card was posted to Slack.
- Expected behavior: Ask for visual_observation/v1 delivery evidence or report delivery as not_observed.
- Why: A prompt card cannot prove generated image, QA, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- source/image
- create/edit
- format
- ratio
- headline or source text
- audience
- language mode
- card sections, source excerpts, or preserve/remove constraints

Expected outputs:

- visual_prompt_card/v1
- image_generation_setup/v1 when generator capability is missing
- source-specific visual format
- detected domain_key
- domain-aware visual theme
- poster_archetype/v1
- poster archetype visual grammar
- background, texture, camera, and lighting direction
- image-safe card copy
- generation prompt
- image transformation brief when editing a supplied image
- negative prompt
- quality checks
- visual evidence boundary
- visual_generation_receipt/v1 when a producer reports an image attempt
- requested route separate from observed route

Artifact expectations:

- visual_prompt_card/v1 prompt card when prepared
- image_generation_setup/v1 fallback when image_generation_capability/v1 is unknown or prompt_only
- visual_observation/v1 only when a wrapper or user records generated image, visual QA, or delivery evidence
- visual_generation_receipt/v1 only when a producer reports one image attempt, with unattested route fields left unknown
