---
name: "omh-image-cards"
description: "[omh] Infographic card for meeting notes, a report, or PR: image prompt cards - turn meetings, reports, PRs, issues, research, and releases into domain-aware image prompt cards. Use when the user says: img-summary, img summary, visual prompt card, image card, image generation, image edit, edit this image, remove the background."
disable-model-invocation: true
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: visual-prompt-card
    role: operator
    quality_tier: visual-card-gated
---

# Img Summary

This is an OMH `img-summary` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`img-summary` exists so Hermes can turn common communication work into provider-neutral image-card prompts while adapting format, domain mood, background, texture, lighting, camera, and poster grammar, and keeping generation, QA, and delivery as observed-only evidence.

## Do Not Use When

- The user needs a deck, PDF, spreadsheet, HWP, Markdown package, or binary file export plan; use `omh-materials-package`.
- The user wants a text-only report, leadership brief, or PPT-ready outline; use `omh-report-package`.
- The user asks OMH to directly generate, inspect, upload, or post an image without a wrapper-supplied observed evidence path.
- A standalone picture with no source material to summarize; call the host image tool with the user's own prompt, no card format.

## Examples

Good example:

- Prompt: img-summary make a PR summary card for reviewers.
- Expected behavior: Prepare visual_prompt_card/v1 with the PR review infographic format, copy mode, generation prompt, negative prompt, and not-evidence boundaries.
- Why: The request asks for an image-card communication artifact, not a PDF/deck package or hidden image generation.

Bad example:

- Prompt: img-summary prove this generated card was posted to Slack.
- Expected behavior: Ask for visual_observation/v1 delivery evidence or report delivery as not_observed.
- Why: A prompt card cannot prove generated image, QA, or delivery evidence.

## Completion Checklist

- The source kind, format, ratio and language mode are named.
- Prompt prepared, image generated, text read back, visual QA and delivery are separate states.

## Recovery Notes

- If image_generation_capability/v1 is unknown or prompt_only, retain visual_prompt_card/v1, mark generation not_observed, and hand back image_generation_setup/v1 with the question of which image tool to use.
- If an edit lacks the supplied image reference or preserve/remove constraints, retain only the supplied edit intent, mark transformation unresolved, and hand back the missing inputs for the image transformation brief.
- If visual_generation_receipt/v1 reports a failed or partial attempt, retain visual_prompt_card/v1 and the receipt's failure stage, mark generation not_observed, and hand back the failed attempt without claiming an image.



## When to Use

Use when Hermes should prepare a source-specific visual or supplied-image edit prompt without claiming generation or transformation.

    Strong routing signals: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image generation`, `image edit`, `edit this image`, `remove the background`, `background removal`, `image generation features`, `image generation support`, `image tool support`, `image feature`, `image features`, `visual generation`, `visual generation support`, `visual card support`, `image summary card`, `summary image`, `summary card`, `explainer image`, `feature explainer image`, `feature explanation image`, `product explainer image`, `product explainer card`, `infographic`, `one-page infographic`, `workflow image`, `workflow card`, `shareable image`, `explain this as an image`, `make an image explaining`, `image explaining the cron feature`, `make an image explaining the cron feature`, `make a visual summary of this PR`, `visual summary`, `picture card`, `meeting notes picture card`, `vertical card`, `vertical summary image`, `vertical image card`, `meeting image`, `meeting summary image`, `conversation summary image`, `meeting notes image`, `pr card`, `pr summary card`, `pull request card`, `review card`, `issue card`, `bug triage card`, `feedback card`, `triage card`, `research card`, `report card`, `report summary card`, `report digest card`, `news briefing card`, `competitor-news briefing card`, `briefing card`, `release announcement image`, `release notes image`, `release notes thumbnail`, `announcement card`, `multilingual img-summary`, `이미지 편집`, `배경 제거`, `회의록 세로 요약 이미지`, `회의 요약 이미지`, `회의록을 보기 좋은 세로 이미지로 요약`, `회의록을 보기 좋은 세로 이미지로 요약해줘`, `세로 이미지로 요약`, `세로 이미지로 요약해줘`, `보기 좋은 세로 이미지`, `PR 요약 카드`, `PR 내용을 리뷰어에게 공유할 이미지 카드`, `PR 내용을 리뷰어에게 공유할 이미지 카드로 만들어줘`, `이슈 트리아지 카드`, `버그 트리아지 카드`, `피드백 카드`, `리포트 요약 카드`, `보고서 요약 카드`, `경쟁사 뉴스 브리핑 카드`, `리서치 브리핑 카드`, `릴리즈 노트 발표 이미지`, `릴리즈 노트 썸네일`, `업데이트 발표 이미지`, `세로 이미지 카드`, `이미지 카드`, `회의록 이미지 카드`, `회의록을 세로 이미지 카드`, `설명 이미지`, `설명하는 인포그래픽`, `기능 설명 이미지`, `기능 소개 이미지`, `인포그래픽`, `인포그래픽 만들어줘`, `이미지 요약 카드`, `요약 이미지`, `요약 카드`, `썸네일`, `썸네일 만들어줘`, `썸네일로 만들어줘`, `카드 이미지`, `이미지로 요약`, `이미지로 요약해줘`, `이미지 생성`, `이미지 생성해줘`, `이미지 만들어줘`, `크론 기능 설명 이미지`, `크론 기능 설명 사진`, `크론 기능 설명 사진 하나 만들어줘`, `사진 카드`, `사진처럼 만들어줘`, `PR 요약 사진`, `공유용 이미지`, `안내 이미지`, `워크플로우 이미지`, `이미지로 설명`, `이미지 하나 만들어줘`, `сделай инфографику`, `инфографика`

## Catalog Metadata

Category: `materials`
Phase: `visual-prompt-card`
Quality tier: `visual-card-gated`
Reasoning demand: `standard`

Quality bar:

- Pick one canonical source kind: meeting, github_pr, issue_feedback, research_briefing, report_summary, or release_announcement.
- Use the source-specific format profile instead of forcing every visual into the same grid.
- Expose the detected `domain_key` so wrappers and users can explain why a domain-specific scene and poster archetype were selected.
- Adapt scene, texture, depth, lighting, camera, motifs, palette, and composition to domains such as security, commerce, sports, fashion, finance, developer work, or research.
- Resolve a poster archetype such as Swiss grid, cinematic key-art, editorial magazine, constructivist photomontage, data infographic, product ad, technical brutalist, museum exhibition, sports event, or luxury lookbook.
- Ask image tools to render the domain-specific environment first, then place readable card modules on top; reject flat vector clipart, plain gradients, generic glass cards, color-swapped templates, and low-detail wallpaper.
- Preserve a stable OMH img-summary format contract: source badge, headline, source-kind subtitle, content modules, evidence footer, and small `OMH generated` mark (on request, delete its clause from the prompt).
- Use long_scroll or extended rows when the card needs a document-style vertical canvas with more sections or denser text.
- Keep visible card text readable and faithful to supplied source or structured sections; do not shrink paragraphs into tiny poster copy.
- Read every visible string back from an observed card and compare it with the card copy; a misspelled name, number or date, or garbled CJK, fails the attempt: regenerate with shorter copy or add the text outside the model.
- Separate prompt prepared, image generated, visual QA passed, and delivered states.
- Bind an image result to the card digest, action, attempt, and content digest, then warn on route mismatch, unknown route, stale card, digest drift, and response reuse rather than resolving any of them.
- For transformations, preserve requested identity, composition, text, and protected regions; verify the observed result against the edit brief before a PASS claim.
- Prefer `img-summary` over `omh-materials-package` only when the request asks for an image, visual card, or summary card.
- Use materials/report workflows only after an observed generated file needs packaging.

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

Safety rules:

- Do not call image providers, LLMs, APIs, or network services from OMH core.
- Do not claim image generation, visual QA, posting, sharing, attachment, or delivery from a prepared prompt card.
- Require visual_observation/v1 before claiming generated image, visual QA, or delivery evidence.
- Report requested route apart from observed route; leave provider, model, quality, operation, dimensions, and credential class unknown unless visual_generation_receipt/v1 attests them.
- Do not infer an observed provider, model, or quality from configuration, capability state, or a returned file.
- A failed or partial visual_generation_receipt/v1 keeps its failure stage and is not generated-image evidence.
- Raw source text may become only an extractive draft; do not fabricate summaries, owners, decisions, test results, or conclusions.
- Show `generate_visual_image` only when wrapper context reports image_generation_capability/v1 as connected, and still treat it as wrapper-owned action rather than evidence.
- When image_generation_capability/v1 is unknown or prompt_only, ask which image tool to use and route to image_generation_setup/v1 instead of pretending generation can start.
- For image edits, require a supplied image reference and state preserve, remove, replace, crop, and output constraints without claiming the source image was loaded.
- On Hermes, report image_generation_capability/v1 as `connected` when `image_generate` is in your tool list or tool_search finds it, since Hermes offers that tool only while an image backend is configured, and as `prompt_only` otherwise; never infer it from a Hermes version, a provider key, or a model name.
- A supplied-image edit goes through that tool only when its own description offers to edit an existing image; when it says text-to-image only, the edit stays a prompt card. A result with `success: true` names the file or URL in `image` and backs one visual_generation_receipt/v1 attempt, with every route field the result does not state left unknown; a generated-image claim still needs visual_observation/v1, and visual QA and delivery stay separate.

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
