---
name: "omh-voice-input"
description: "[omh] Dictated voice note about project work or status: terse voice and mobile-style requests - turn short spoken-style asks into clarify, plan, status."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, accessibility]
    category: accessibility
    phase: voice-routing
    role: guide
    quality_tier: workflow-surface-gated
---

# Voice Operator

This is an OMH `voice-operator` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`voice-operator` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- The speech is material to transcribe or summarize; use `omh-media-input`.

## Examples

Good example:

- Prompt: voice-operator 'release before lunch, check risky parts' from mobile.
- Expected behavior: Produce `prepare_voice_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: voice-operator assume the user approved a destructive action from a vague voice note.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The short-input or voice-like request is clarified enough to avoid accidental action.
- Before a delete, send, deploy or spend, state the transcript's names, numbers, paths and negations and wait for a yes.
- The next action is readable, reversible when possible, and confirmation-gated when risky.
- Delivery, notification, or platform behavior is not claimed without wrapper evidence.

## Recovery Notes

- If a dictated request names no target context, nothing is actionable yet; mark the next action unresolved and hand back one target question before preparing voice-operator/v1.
- If a clarified voice request still lacks confirmation for a risky action, retain the voice-operator/v1 guidance, mark execution not_observed, and hand back the proposed next action for explicit approval.



## When to Use

Use when Hermes receives terse voice/mobile-style requests and should produce concise clarification, plan, or status UX.

    Strong routing signals: `voice-operator`, `voice operator`, `voice-first`, `voice command`, `mobile command`, `short command`, `dictated command`, `dictated request`, `spoken request`, `speech command`, `hands free`, `hands-free`, `phone command`, `phone request`, `push command`, `음성`, `음성으로`, `음성 명령`, `모바일 명령`, `모바일 음성`, `핸드폰`, `폰으로`, `말로`, `말로 한 요청`, `짧은 명령`, `짧게 말한 요청`

## Catalog Metadata

Category: `accessibility`
Phase: `voice-routing`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

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

- voice-operator/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- voice-operator/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- A voice operator card is not speech recognition, mobile notification delivery, platform action, or accepted execution evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.
- This card is not realtime voice connector readiness. It may read the tool-safety verdict of a supplied realtime_voice_trial_receipt/v1 when one exists, and it never creates, infers, or upgrades one; route realtime voice adoption to `omh-external-connector-readiness`.

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
