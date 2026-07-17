---
name: img-summary
description: [omh] Hermes img-summary workflow: turn meetings, reports, PRs, issues, research, and releases into domain-aware image prompt cards.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: visual-prompt-card
    role: operator
    quality_tier: visual-card-gated
---

# Img Summary

This is a Hermes-native `img-summary` workflow skill.

## Why This Exists

`img-summary` exists so Hermes can turn common communication work into provider-neutral image-card prompts while adapting format, domain mood, background, texture, lighting, camera, and poster grammar, and keeping generation, QA, and delivery as observed-only evidence.

## Do Not Use When

- The user needs a deck, PDF, spreadsheet, HWP, Markdown package, or binary file export plan; use `materials-package`.
- The user wants a text-only report, leadership brief, or PPT-ready outline; use `report-package`.
- The user asks OMH to directly generate, inspect, upload, or post an image without a wrapper-supplied observed evidence path.

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

- The material source, target format, audience, structure, and QA expectation are named.
- Binary export, rendering, formula recalculation, attachment, and delivery stay observed-only.
- The next action identifies whether the package is planned, generated, QA-ready, or blocked.

## Recovery Notes

- If a renderer or file tool is missing, keep the package prepared and expose the generation handoff.
- If render QA is unavailable, mark the artifact unverified and request the smallest visual/file check.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-orchestration`, `design-quality-gate`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `media-input-operator`, `materials-package`, `+3 more`) - web, accessibility, visual QA, files, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should prepare a source-specific visual or supplied-image edit prompt without claiming generation or transformation.

    Strong routing signals: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image generation`, `image edit`, `edit this image`, `remove the background`, `background removal`, `이미지 편집`, `배경 제거`, `image generation features`, `image generation support`, `image tool support`, `image feature`, `image features`, `visual generation`, `visual generation support`, `visual card support`, `image summary card`, `summary image`, `summary card`, `explainer image`, `feature explainer image`, `feature explanation image`, `product explainer image`, `product explainer card`, `infographic`, `one-page infographic`, `workflow image`, `workflow card`, `shareable image`, `explain this as an image`, `make an image explaining`, `image explaining the cron feature`, `make an image explaining the cron feature`, `make a visual summary of this PR`, `visual summary`, `picture card`, `meeting notes picture card`, `vertical card`, `vertical summary image`, `vertical image card`, `meeting image`, `meeting summary image`, `conversation summary image`, `meeting notes image`, `pr card`, `pr summary card`, `pull request card`, `review card`, `issue card`, `bug triage card`, `feedback card`, `triage card`, `research card`, `report card`, `report summary card`, `report digest card`, `news briefing card`, `competitor-news briefing card`, `briefing card`, `release announcement image`, `release notes image`, `release notes thumbnail`, `announcement card`, `multilingual img-summary`, `회의록 세로 요약 이미지`, `회의 요약 이미지`, `회의록을 보기 좋은 세로 이미지로 요약`, `회의록을 보기 좋은 세로 이미지로 요약해줘`, `세로 이미지로 요약`, `세로 이미지로 요약해줘`, `보기 좋은 세로 이미지`, `PR 요약 카드`, `PR 내용을 리뷰어에게 공유할 이미지 카드`, `PR 내용을 리뷰어에게 공유할 이미지 카드로 만들어줘`, `이슈 트리아지 카드`, `버그 트리아지 카드`, `피드백 카드`, `리포트 요약 카드`, `보고서 요약 카드`, `경쟁사 뉴스 브리핑 카드`, `리서치 브리핑 카드`, `릴리즈 노트 발표 이미지`, `릴리즈 노트 썸네일`, `업데이트 발표 이미지`, `세로 이미지 카드`, `이미지 카드`, `회의록 이미지 카드`, `회의록을 세로 이미지 카드`, `설명 이미지`, `설명하는 인포그래픽`, `기능 설명 이미지`, `기능 소개 이미지`, `인포그래픽`, `인포그래픽 만들어줘`, `이미지 요약 카드`, `요약 이미지`, `요약 카드`, `썸네일`, `썸네일 만들어줘`, `썸네일로 만들어줘`, `카드 이미지`, `이미지로 요약`, `이미지로 요약해줘`, `이미지 생성`, `이미지 생성해줘`, `이미지 만들어줘`, `크론 기능 설명 이미지`, `크론 기능 설명 사진`, `크론 기능 설명 사진 하나 만들어줘`, `사진 카드`, `사진처럼 만들어줘`, `PR 요약 사진`, `공유용 이미지`, `안내 이미지`, `워크플로우 이미지`, `이미지로 설명`, `이미지 하나 만들어줘`

## Catalog Metadata

Category: `materials`
Phase: `visual-prompt-card`
Hermes role: `operator`
Quality tier: `visual-card-gated`

Quality bar:

- Pick one canonical source kind: meeting, github_pr, issue_feedback, research_briefing, report_summary, or release_announcement.
- Use the source-specific format profile instead of forcing every visual into the same grid.
- Expose the detected `domain_key` so wrappers and users can explain why a domain-specific scene and poster archetype were selected.
- Adapt scene, texture, depth, lighting, camera, motifs, palette, and composition to domains such as security, commerce, sports, fashion, finance, developer work, or research.
- Resolve a poster archetype such as Swiss grid, cinematic key-art, editorial magazine, constructivist photomontage, data infographic, product ad, technical brutalist, museum exhibition, sports event, or luxury lookbook.
- Ask image tools to render the domain-specific environment first, then place readable card modules on top; reject flat vector clipart, plain gradients, generic glass cards, color-swapped templates, and low-detail wallpaper.
- Preserve a stable OMH img-summary format contract: source badge, headline, source-kind subtitle, content modules, evidence footer, and small `OMH generated` mark.
- Use long_scroll or extended rows when the card needs a document-style vertical canvas with more sections or denser text.
- Keep visible card text readable and faithful to supplied source or structured sections; do not shrink paragraphs into tiny poster copy.
- Separate prompt prepared, image generated, visual QA passed, and delivered states.
- For transformations, preserve requested identity, composition, text, and protected regions; verify the observed result against the edit brief before a PASS claim.
- Prefer `img-summary` over `materials-package` only when the request asks for an image, visual card, or summary card.
- Use materials/report workflows only after an observed generated file needs packaging.

Handoff policy:

Keep card copy shaping, source-kind selection, language mode, prompt assembly, and evidence narration in Hermes. Use wrapper-reported image generation only as an optional action; record generated image, visual QA, and delivery claims only from visual_observation/v1 evidence.

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

Artifact expectations:

- visual_prompt_card/v1 prompt card when prepared
- image_generation_setup/v1 fallback when image_generation_capability/v1 is unknown or prompt_only
- visual_observation/v1 only when a wrapper or user records generated image, visual QA, or delivery evidence

Safety rules:

- Do not call image providers, LLMs, APIs, or network services from OMH core.
- Do not claim image generation, visual QA, posting, sharing, attachment, or delivery from a prepared prompt card.
- Require visual_observation/v1 before claiming generated image, visual QA, or delivery evidence.
- Raw source text may become only an extractive draft; do not fabricate summaries, owners, decisions, test results, or conclusions.
- Show `generate_visual_image` only when wrapper context reports image_generation_capability/v1 as connected, and still treat it as wrapper-owned action rather than evidence.
- When image_generation_capability/v1 is unknown or prompt_only, ask which image tool to use and route to image_generation_setup/v1 instead of pretending generation can start.
- For image edits, require a supplied image reference and state preserve, remove, replace, crop, and output constraints without claiming the source image was loaded.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `img-summary`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill img-summary --harness img-summary --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
