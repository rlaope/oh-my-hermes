---
name: "omh-show-reel"
description: "[omh] Video to make from an idea or a product: an explainer, motion graphics, kinetic type, a logo intro, a 3D scene, a data-viz animation, a music visual, a short or a source-grounded product film, authored and rendered to a measured MP4 with locale/export QA and source delivery. Use when the user says: show-reel, show reel, showreel, product showcase video, animated product film, motion showcase, animated portfolio, launch film."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, design]
    category: design
    phase: motion-production
    role: operator
    quality_tier: evidence-gated
    related_skills: [omh-image-cards, omh-frontend, omh-media-input, manim-video, ascii-video, omh-materials-package, omh-design-quality-gate, omh-visual-qa]
---

# Show Reel

## Why This Exists

`show-reel` owns the motion-production method for every authored video, from a 20-second idea explainer to a product film, so factual claims, visual decisions, locale timing, revision budget, measured exports, and delivery receipts cannot drift apart. It does not render inside OMH core.

## First Steps

- Pick the lane first. A video from an idea with no product claim, real UI or brand asset on screen takes the idea lane in `## Idea Videos` below; a product, launch, brand or work film, or any product fact on screen, takes the full method.
- Read `references/brief-and-locales.md` and `references/storyboard-and-evidence.md` before proposing visuals. Recover objective, audience, channel, duration, aspect ratio, fps, size cap, source/brand permissions, and tool availability from supplied context; honor explicit format and duration, ask only for irretrievable hard facts, and label reversible creative assumptions. A shot of a UI that exists is drawn from that product's own renderer output, never a look-alike, and every product fact on screen is copied from its canonical source and cited.
- Resolve content language from current explicit user/audience/channel instructions, then applicable stable preferences, then user language. Keep reply_language under host persona and separate content_locale, onscreen_text, subtitle_text, pronunciation_text, voice_policy, font_policy, and direction_policy; never replace literal IDs, commands, URLs, or trademarks.
- For a product, brand or work film, compare at least 3 genuinely distinct concept candidates before selection; record the rubric, winner, rejected alternatives, and per-segment art direction. Read `references/craft-workflow.md` (the full upstream production method), `toolkit/README.md` under the loaded skill directory with a file reader, then `references/renderer-adapter.md` before choosing tools; a missing renderer means HOLD on a requested video, not a completed delivery.
- If the reel is captured from a game or simulation instead of authored from static assets, read `references/game-capture.md` before capture and timeline authoring: run the simulate → capture → timeline.json → finish edit pipeline with `timeline.json` as the single source of truth for events, SFX cues and titles, pin and record the source game data version/build, map every gameplay event that needs SFX to a cue in timeline.json (an unmapped event is HOLD), apply the shorts defaults (1080x1920, black letterbox bars, centered white title, fade-in, tuned BGM start offset) only as brief-overridable defaults, and record voice provenance (source clip URL, sha256, excerpt range) for any real voice — never synthesizing an impersonation of a real voice actor or person and labeling timbre-alike or synthetic voice methods honestly in credits, with performer/IP permissions handled in the existing assets-and-rights flow.

## Idea Videos

An explainer, motion graphics, kinetic type, a logo or title intro, a 3D scene, a data-viz animation, a music visual or a short, with no product claim, real UI or brand asset on screen, takes this lane. It skips the source register, the rights register and the 3-concept comparison; it never skips a render.

- Defaults, each labeled as an assumption and overridden by anything the user said: 16:9 1920x1080, 30 fps, 20-30 s when no duration is given (about 2.5 s per beat), muted unless music is asked for, on-screen text in the user's language. Ask only for a fact that cannot be recovered.
- Pick one concept from its genre recipe in `references/genres.md` and record its assumptions. Then author one HTML composition with a deterministic time seek (a paused GSAP timeline or a `__seek(t)` function; no `Math.random()` or wall clock).
- Probe the renderer read-only, in the order `references/genres.md` gives: the `hyperframes` CLI only when `command -v hyperframes` finds it (`npx` would download it), then `toolkit/scripts/render.mjs` with a local Chrome, `puppeteer-core` and FFmpeg, then a frame renderer already installed (such as Python with Pillow) piped to FFmpeg. If none runs, HOLD with the exact install command and ask for consent once; never install, download fonts or call a paid API on your own.
- Render 3 style frames and view them, render a draft, view its contact sheet, and rebuild the weakest beat once. Export, then measure codec, dimensions, fps, duration, size and sha256 with `ffprobe`; deliver the path with those facts. A storyboard or an HTML file alone is HOLD, not delivery.
- Fill the frame, use one hue family plus at most one accent, add no meta text (window titles, dimension labels, invented paths), draw no rounded "document" cards as a metaphor, and move the camera on one continuous path rather than stopping at every beat.
- A product claim, a real UI or a brand asset on screen moves the video to the full method below.

**Do Not Use When:** A math proof, equation or algorithm animation in the 3Blue1Brown style belongs to Hermes' bundled `manim-video` skill; converting existing footage to ASCII art belongs to `ascii-video`.

## Production Method

Read `references/procedure.md` for the ordered brief → source verification → concept selection → segment direction → measured timing → authored motion → critique/revision → export → QA → delivery method. `references/full-contract.md` owns boundaries, quality and completion criteria; read it before production, not after export.

Require actual style frames and moving draft playback, keep/fix/rebuild critique and a weakest-scene revision budget. Inspect the final encoded artifact at delivery-size; no tiny crowded labels or PASS from full-resolution stills alone. Requested video, codec/color/filesize, cut/motion, localization and source-package checks need observed receipts or remain HOLD.

Required: objective/audience/channel, explicit duration/format/budget, source/brand rights and available tools. Outputs: brief, source register, concept selection, storyboard, timing map, renderer handoff, preview review, export, QA and delivery manifests. These are authored contracts, not new executable schemas or core runtime operations. Missing renderer permits useful preparation, never a completed video claim.

## When to Use

Use when a user wants a video authored from an idea or a product: an explainer of how something works, motion graphics or kinetic type, a logo or title intro, a 3D scene, a data-viz animation, a music visual, a short or vertical version, or a product, launch or work showcase, from the brief to a rendered, measured MP4, localized variants and source delivery.

## Catalog Metadata

Category: `design`. Phase: `motion-production`. Hermes role: `operator`. Quality tier: `evidence-gated`. Detailed quality and authority checks: `references/full-contract.md`.

## Completion Checklist

- Load the full-contract checklist and `references/render-qa-delivery.md` before claiming completion; separate generated, attached, received and published.
- Preserve the user's stop conditions, language choices and literal tokens. Keep the host's reply language and persona independent of content language.
- Report actual files, source package, observed checks and every missing required check; publication and spending need separate exact-target approval.

## Recovery Notes

- If source rights, audience facts or explicit requirements conflict, HOLD and ask only the decision-changing question. Label reversible creative assumptions instead of blocking on them.
- Missing renderer/font/voice or failed/partial exports remain visible; do not install tools, call APIs or fabricate receipts.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`show-reel`, `sprite-forge`, `design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `+8 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Runtime Evidence

Preferred harness for this skill: `show-reel`.

```sh
omh runtime record --skill show-reel --harness show-reel --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
