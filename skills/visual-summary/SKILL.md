---
name: visual-summary
description: [omh] Hermes Visual Summary workflow: turn meetings, PRs, issues, research, and release notes into image-generation-ready visual prompt cards.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: visual-prompt-card
    role: operator
    quality_tier: visual-card-gated
---

# Visual Summary

This is a Hermes-native `visual-summary` workflow skill.

## Why This Exists

`visual-summary` exists so Hermes can turn common communication work into provider-neutral image-card prompts while keeping generation, QA, and delivery as observed-only wrapper or user evidence.

## Do Not Use When

- The user needs a deck, PDF, spreadsheet, HWP, Markdown package, or binary file export plan; use `materials-package`.
- The user wants a text-only report, leadership brief, or PPT-ready outline; use `report-package`.
- The user asks OMH to directly generate, inspect, upload, or post an image without a wrapper-supplied observed evidence path.

## Examples

Good example:

- Prompt: visual-summary make a PR summary card for reviewers.
- Expected behavior: Prepare visual_prompt_card/v1 with PR-specific sections, copy mode, generation prompt, negative prompt, and not-evidence boundaries.
- Why: The request asks for an image-card communication artifact, not a PDF/deck package or hidden image generation.

Bad example:

- Prompt: visual-summary prove this generated card was posted to Slack.
- Expected behavior: Ask for visual_observation/v1 delivery evidence or report delivery as not_observed.
- Why: A prompt card cannot prove generated image, QA, or delivery evidence.

## Use When

Use when Hermes should shape supplied notes, PR context, issue feedback, research/news, or release notes into a readable vertical image-card prompt without claiming image generation.

    Strong routing signals: `visual-summary`, `visual summary`, `visual prompt card`, `image card`, `summary image`, `vertical card`, `vertical summary image`, `meeting image`, `meeting summary image`, `conversation summary image`, `meeting notes image`, `pr card`, `pr summary card`, `pull request card`, `review card`, `issue card`, `bug triage card`, `feedback card`, `triage card`, `research card`, `news briefing card`, `competitor-news briefing card`, `briefing card`, `release announcement image`, `release notes image`, `announcement card`, `multilingual visual summary`, `회의록 세로 요약 이미지`, `회의 요약 이미지`, `PR 요약 카드`, `이슈 트리아지 카드`, `버그 트리아지 카드`, `피드백 카드`, `경쟁사 뉴스 브리핑 카드`, `리서치 브리핑 카드`, `릴리즈 노트 발표 이미지`, `업데이트 발표 이미지`

## Catalog Metadata

Category: `materials`
Phase: `visual-prompt-card`
Hermes role: `operator`
Quality tier: `visual-card-gated`

Quality bar:

- Pick one canonical source kind: meeting, github_pr, issue_feedback, research_briefing, or release_announcement.
- Keep visible card text short, readable, and faithful to supplied source or structured sections.
- Separate prompt prepared, image generated, visual QA passed, and delivered states.
- Prefer `visual-summary` over `materials-package` only when the request asks for an image, visual card, or summary card.
- Use materials/report workflows only after an observed generated file needs packaging.

Handoff policy:

Keep card copy shaping, source-kind selection, language mode, prompt assembly, and evidence narration in Hermes. Use wrapper-reported image generation only as an optional action; record generated image, visual QA, and delivery claims only from visual_observation/v1 evidence.

Required inputs:

- source kind
- headline or source text
- audience
- language mode
- card sections or supplied source excerpts

Expected outputs:

- visual_prompt_card/v1
- image-safe card copy
- generation prompt
- negative prompt
- quality checks
- visual evidence boundary

Artifact expectations:

- visual_prompt_card/v1 prompt card when prepared
- visual_observation/v1 only when a wrapper or user records generated image, visual QA, or delivery evidence

Safety rules:

- Do not call image providers, LLMs, APIs, or network services from OMH core.
- Do not claim image generation, visual QA, posting, sharing, attachment, or delivery from a prepared prompt card.
- Require visual_observation/v1 before claiming generated image, visual QA, or delivery evidence.
- Raw source text may become only an extractive draft; do not fabricate summaries, owners, decisions, test results, or conclusions.
- Show `generate_visual_image` only when wrapper context reports image_generation_capability/v1 as connected, and still treat it as wrapper-owned action rather than evidence.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `visual-summary`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill visual-summary --harness visual-summary --status started
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
