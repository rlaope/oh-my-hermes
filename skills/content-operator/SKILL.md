---
name: content-operator
description: [omh] Hermes content operator workflow: scope publish-ready writing, rewriting, summarization, translation, release-note, newsletter, customer-copy, social-copy, README-copy, and email-draft work with audience, tone, style, source, review, and hallucination gates.
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

- If the request asks for citations, current facts, or source-backed evidence gathering, route to web-research or source-finder before drafting.
- If the request asks to send, post, invite, ticket, or mutate an external app, route to connector-operator before claiming delivery.
- If the request asks for PDF, PPT, DOCX, HWP, spreadsheet, or attachment packaging, route to materials-package or deliverable-package.
- If the request is a simple one-off sentence or paragraph transformation, answer directly instead of opening a workflow.

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

Use when Hermes should prepare or supervise quality-controlled content creation or transformation without claiming source access, fact verification, stakeholder approval, publishing, sending, file export, or delivery.

    Strong routing signals: `content-operator`, `content operator`, `content workflow`, `writing workflow`, `publish-ready writing`, `publish ready writing`, `release notes`, `release note draft`, `newsletter draft`, `customer announcement`, `customer copy`, `product copy`, `landing page copy`, `social post draft`, `email draft`, `draft an email`, `rewrite for executives`, `summarize for customers`, `style guide rewrite`, `audience and tone`, `tone of voice`, `콘텐츠 오퍼레이터`, `글쓰기 워크플로`, `릴리즈 노트`, `릴리즈노트`, `뉴스레터 초안`, `고객 공지문`, `고객 공지`, `고객용 요약`, `메일 초안`, `이메일 초안`, `채널별 톤`, `문체 가이드`

## Catalog Metadata

Category: `content`
Phase: `content-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`

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

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `content-operator`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill content-operator --harness content-operator --status started
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
