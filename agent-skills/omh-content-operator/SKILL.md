---
name: "omh-content-operator"
description: "[omh] Product or company copy to publish or rewrite: scope publish-ready writing, rewriting, summarization, translation, release-note, newsletter, customer-copy, social-copy, README-copy, and email-draft work with audience, tone, style, source, review, and hallucination gates. Use when the user says: content-operator, content operator, content workflow, writing workflow, publish-ready writing, publish ready writing, release notes, release note draft."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, content]
    category: content
    phase: content-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Content Operator

This is an OMH `content-operator` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`content-operator` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

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
- Every product fact in the copy (install command, command and flag names, package name, URL, version, count) is copied byte-for-byte from its canonical source, such as the README install block, `--help` output, or the producer of the count, and cited by path; a fact written from memory or an earlier draft is a fact-risk, not a fact.
- Every count the copy generates agrees with its noun in each plural category of the content locale (0, 1, and 2 for English: `0 agents`, `1 agent`, `2 agents`) before it ships.

## Recovery Notes

- If the request asks for citations, current facts, or source-backed evidence gathering, route to research or source-finder before drafting.
- If the request asks to send, post, invite, ticket, or mutate an external app, route to connector-operator before claiming delivery.
- If the request asks for PDF, PPT, DOCX, HWP, spreadsheet, or attachment packaging, route to materials-package or deliverable-package.
- If the request is a simple one-off sentence or paragraph transformation, answer directly instead of opening a workflow.



## When to Use

Use when Hermes should prepare or supervise quality-controlled content creation or transformation without claiming source access, fact verification, stakeholder approval, publishing, sending, file export, or delivery.

    Strong routing signals: `content-operator`, `content operator`, `content workflow`, `writing workflow`, `publish-ready writing`, `publish ready writing`, `release notes`, `release note draft`, `newsletter draft`, `customer announcement`, `customer copy`, `product copy`, `landing page copy`, `social post draft`, `email draft`, `draft an email`, `rewrite for executives`, `summarize for customers`, `style guide rewrite`, `audience and tone`, `tone of voice`, `콘텐츠 오퍼레이터`, `글쓰기 워크플로`, `릴리즈 노트`, `릴리즈노트`, `뉴스레터 초안`, `고객 공지문`, `고객 공지`, `고객용 요약`, `메일 초안`, `이메일 초안`, `채널별 톤`, `문체 가이드`

## Catalog Metadata

Category: `content`
Phase: `content-task`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

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
