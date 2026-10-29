# Show Reel

Load this on-demand contract after the compact `show-reel` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Do Not Use When

- Only a static infographic or summary card is needed; use `omh-image-cards`.
- The request is a website, landing page or interactive UI build, or an animation inside an app's own UI (a button, modal, page transition or loading state); use `omh-frontend`.
- Summarizing, transcribing, captioning or trimming a recording that already exists; use `omh-media-input`.
- A math proof, equation or algorithm animation in the 3Blue1Brown style belongs to Hermes' bundled `manim-video` skill; converting existing footage to ASCII art belongs to `ascii-video`.
- The output is a deck, PDF, spreadsheet or office document; use `omh-materials-package`.
- Only a premium layout quality assessment is wanted; use `omh-design-quality-gate`.
- The user already has rendered frames and needs a visual verdict, not new production; use `omh-visual-qa`.
- Routine trimming, file conversion, live broadcasting, fishing equipment, tape storage, film criticism and social posting alone do not need this method.

## Examples

Good example:

- Prompt: Create a 20-second muted product showcase video for a Japanese audience using these approved screenshots and English brand names.
- Expected behavior: Verify sources and locale, compare three concepts, direct segments, author motion with available tools, inspect the measured export, and deliver sources with honest gaps.
- Why: An authored time-based showcase needs one coherent production method, not only an image prompt or critique.

Bad example:

- Prompt: Convert this existing clip to a smaller MP4.
- Expected behavior: Use a scoped media conversion tool; do not begin concept development.
- Why: An existing file conversion is not an authored showcase.

## Completion Checklist

- Brief, source rights, selected concept and per-segment art direction exist; current explicit audience language beats stable preferences and user language, with reply and each content track kept separate.
- Actual style frames, draft playback, keep/fix/rebuild, weakest-scene revision and delivery-size checks are observed or HOLD; codec/color/filesize, cuts, motion and locale QA are not inferred from file existence.
- Requested video and source package are generated and transferred only when receipts exist; source package is reproducible and rights-cleared, and every missing evidence item remains named.

## Recovery Notes

- If sources, rights or irretrievable audience facts conflict, HOLD and ask one decision-changing question; label creative assumptions rather than interviewing for every aesthetic choice.
- If font, renderer or voice capability is unavailable, return the useful storyboard and source handoff but keep the requested video HOLD; offer a subtitle-only or available-tool alternative without silently changing scope.
- If revision budget is exhausted or export/transfer fails, keep the last observed partial state, exact defect and next repair; do not claim completion or retry an external mutation blindly.



## Workflow Contract

Category: `design`
Phase: `motion-production`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- A product, brand or work film requires at least 3 distinct concept candidates, per-segment art direction and source-grounded motion; an idea video selects one concept with recorded assumptions. Never force a fixed palette or visual style, and let an explicit duration, format or audio request override every idea-lane default.
- Use keep/fix/rebuild critique and a weakest-scene revision budget; reject repeated headline/card/rail grammar, require delivery-size moving evidence and both rebuilt cut boundaries. Technical metrics never fill independent artistic, playback or listening verdicts.
- Read `references/assets-and-rights.md`, `references/render-qa-delivery.md` and `references/source-package.md` before export and delivery; missing required evidence keeps HOLD, never fabricated success.

Handoff policy:

Keep brief, source verification, concept selection, storyboard, critique, and evidence synthesis with the current host. Use only explicitly selected available production tools in an approved workspace. Load `references/procedure.md` for the ordered method and the production references for working templates; the optional local toolkit is declared data, never automatically executed. A prepared handoff is not a render, translation review, listening check, attachment, or publication; never add a core render command.

Required inputs:

- objective audience and channel
- duration format and budget
- source brand and asset permissions
- available production tools

Expected outputs:

- show_reel_brief/v1
- show_reel_source_asset_register/v1
- show_reel_concept_selection/v1
- show_reel_storyboard/v1
- show_reel_timing_map/v1
- show_reel_renderer_handoff/v1
- show_reel_preview_review/v1
- show_reel_export_manifest/v1
- show_reel_qa_report/v1
- show_reel_delivery_manifest/v1

Artifact expectations:

- Keep media, source files and authored text in the approved project folder; durable OMH records contain only bounded safe references, digests, states and gaps, never raw media, private source text or credentials.

Safety rules:

- No automatic network/model/API calls, subprocess execution, dependency installation, font downloads, account discovery, voice cloning or paid defaults inside core; every chosen external action needs scope and authority.
- A renderer unavailable, timeout, pageerror, missing font or partial export is HOLD or failed, never successful delivery. Never invent a tool receipt, translation, listening review or product capture.
- Use user/official/rights-cleared assets first; generated visuals carry generation provenance and concept labels. Publish/spend/voice cloning requires separate explicit consent and exact-target approval.

Detailed procedure steps: `references/procedure.md`.
