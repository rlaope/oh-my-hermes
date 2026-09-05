---
name: "omh-content-operator"
description: "[omh] Hermes content operator workflow: scope publish-ready writing, rewriting, summarization, translation, release-note, newsletter, customer-copy, social-copy, README-copy, and email-draft work with audience, tone, style, source, review, and hallucination gates. Use when the user says: content-operator, content operator, content workflow, writing workflow, publish-ready writing, publish ready writing, release notes, release note draft."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, content]
    category: content
    phase: content-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Content Operator

This is a Hermes-native `content-operator` workflow skill.

## Why This Exists

`content-operator` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: content-operator draft publish-ready release notes with audience, tone, source scope, review gates, and hallucination checks.
- Expected behavior: Produce `prepare_content_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: content-operator invent missing facts and claim the customer announcement was sent.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Audience, channel, language, tone, style guide, length, source scope, fact-risk, review owner, and stop condition are explicit.
- Missing facts, source gaps, claims needing citations, legal/compliance needs, approval, publish/send authority, and file-export needs are gated or marked missing.
- Published, sent, exported, approved, and fact-verified claims are reported only from observed evidence.

## Recovery Notes

- If the request asks for citations, current facts, or source-backed evidence gathering, route to research or source-finder before drafting.
- If the request asks to send, post, invite, ticket, or mutate an external app, route to connector-operator before claiming delivery.
- If the request asks for PDF, PPT, DOCX, HWP, spreadsheet, or attachment packaging, route to materials-package or deliverable-package.
- If the request is a simple one-off sentence or paragraph transformation, answer directly instead of opening a workflow.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `+6 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should prepare or supervise quality-controlled content creation or transformation without claiming source access, fact verification, stakeholder approval, publishing, sending, file export, or delivery.

    Strong routing signals: `content-operator`, `content operator`, `content workflow`, `writing workflow`, `publish-ready writing`, `publish ready writing`, `release notes`, `release note draft`, `newsletter draft`, `customer announcement`, `customer copy`, `product copy`, `landing page copy`, `social post draft`, `email draft`, `draft an email`, `rewrite for executives`, `summarize for customers`, `style guide rewrite`, `audience and tone`, `tone of voice`, `콘텐츠 오퍼레이터`, `글쓰기 워크플로`, `릴리즈 노트`, `릴리즈노트`, `뉴스레터 초안`, `고객 공지문`, `고객 공지`, `고객용 요약`, `메일 초안`, `이메일 초안`, `채널별 톤`, `문체 가이드`

## Catalog Metadata

Category: `content`
Phase: `content-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

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

Safety rules:

- A content operator card is not source retrieval, fact verification, hallucination-free copy, stakeholder approval, publishing, email/message sending, file export, delivery, or proof that final copy was accepted unless observed content output evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `content-operator`.

```sh
omh runtime record --skill content-operator --harness content-operator --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
