---
name: "omh-show-reel"
description: "[omh] Video to make from an idea or a product: an explainer, motion graphics, kinetic type, a logo intro, a 3D scene, a data-viz animation, a music visual, a short or a source-grounded product film, authored and rendered to a measured MP4 with locale/export QA and source delivery. Use when the user says: show-reel, show reel, showreel, product showcase video, animated product film, motion showcase, animated portfolio, launch film."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, design]
    category: design
    phase: motion-production
    role: operator
    quality_tier: evidence-gated
---

# Show Reel

This is an OMH `show-reel` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`show-reel` owns the motion-production method for every authored video, from a 20-second idea explainer to a product film, so factual claims, visual decisions, locale timing, revision budget, measured exports, and delivery receipts cannot drift apart. It does not render inside OMH core.

## First Steps

- Pick the lane first. A video from an idea with no product claim, real UI or brand asset on screen takes the idea lane in `## Idea Videos` below; a product, launch, brand or work film, or any product fact on screen, takes the full method.
- Read `references/brief-and-locales.md` and `references/storyboard-and-evidence.md` before proposing visuals. Recover objective, audience, channel, duration, aspect ratio, fps, size cap, source/brand permissions, and tool availability from supplied context; honor explicit format and duration, ask only for irretrievable hard facts, and label reversible creative assumptions. A shot of a UI that exists is drawn from that product's own renderer output, never a look-alike, and every product fact on screen is copied from its canonical source and cited.
- Resolve content language from current explicit user/audience/channel instructions, then applicable stable preferences, then user language. Keep reply_language under host persona and separate content_locale, onscreen_text, subtitle_text, pronunciation_text, voice_policy, font_policy, and direction_policy; never replace literal IDs, commands, URLs, or trademarks.
- For a product, brand or work film, compare at least 3 genuinely distinct concept candidates before selection; record the rubric, winner, rejected alternatives, and per-segment art direction. Read `references/craft-workflow.md` (the full upstream production method), `toolkit/README.md` under the loaded skill directory with a file reader, then `references/renderer-adapter.md` before choosing tools; a missing renderer means HOLD on a requested video, not a completed delivery.
- If the reel is captured from a game or simulation instead of authored from static assets, read `references/game-capture.md` before capture and timeline authoring: run the simulate → capture → timeline.json → finish edit pipeline with `timeline.json` as the single source of truth for events, SFX cues and titles, pin and record the source game data version/build, map every gameplay event that needs SFX to a cue in timeline.json (an unmapped event is HOLD), apply the shorts defaults (1080x1920, black letterbox bars, centered white title, fade-in, tuned BGM start offset) only as brief-overridable defaults, and record voice provenance (source clip URL, sha256, excerpt range) for any real voice — never synthesizing an impersonation of a real voice actor or person and labeling timbre-alike or synthetic voice methods honestly in credits, with performer/IP permissions handled in the existing assets-and-rights flow.

## Do Not Use When

- Only a static infographic or summary card is needed; use `omh-image-cards`.
- The request is a website, landing page or interactive UI build, or an animation inside an app's own UI (a button, modal, page transition or loading state); use `omh-frontend`.
- Summarizing, transcribing, captioning or trimming a recording that already exists; use `omh-media-input`.
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



## When to Use

Use when a user wants a video authored from an idea or a product: an explainer of how something works, motion graphics or kinetic type, a logo or title intro, a 3D scene, a data-viz animation, a music visual, a short or vertical version, or a product, launch or work showcase, from the brief to a rendered, measured MP4, localized variants and source delivery.

    Strong routing signals: `show-reel`, `show reel`, `showreel`, `product showcase video`, `animated product film`, `motion showcase`, `animated portfolio`, `launch film`, `product teaser video`, `promo video`, `promotional video`, `launch video`, `product launch video`, `product video`, `teaser video`, `sizzle reel`, `hyperframes video`, `motion graphics`, `kinetic typography`, `logo intro animation`, `music visualizer`, `製品ショーケース動画`, `제품 쇼케이스 영상`, `产品展示短片`

## Catalog Metadata

Category: `design`
Phase: `motion-production`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- A product, brand or work film requires at least 3 distinct concept candidates, per-segment art direction and source-grounded motion; an idea video selects one concept with recorded assumptions. Never force a fixed palette or visual style, and let an explicit duration, format or audio request override every idea-lane default.
- Use keep/fix/rebuild critique and a weakest-scene revision budget; reject repeated headline/card/rail grammar, require delivery-size moving evidence and both rebuilt cut boundaries. Technical metrics never fill independent artistic, playback or listening verdicts.
- Read `references/assets-and-rights.md`, `references/render-qa-delivery.md` and `references/source-package.md` before export and delivery; missing required evidence keeps HOLD, never fabricated success.

Required inputs:

- objective audience and channel
- duration format and budget
- source brand and asset permissions
- available production tools

Expert clarification questions:
- `objective audience and channel`
  - English: Who should watch this, on which channel, in which content language, and what should they understand or do?
  - Korean: 누가 어떤 채널에서 어떤 언어로 보고 무엇을 이해하거나 행동해야 하나요?

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

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
