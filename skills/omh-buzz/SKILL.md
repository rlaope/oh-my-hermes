---
name: "omh-buzz"
description: "[omh] Buzz community agent setup or relay trouble: connect and operate Hermes as a native Buzz community agent, deliver local media with verified relay receipts, or diagnose a self-hosted Buzz relay without inventing transport evidence. Aliases: omh-buzz. Use when the user says: connect Hermes to Buzz, Buzz community agent, Buzz gateway setup, Buzz media attachment, Buzz relay self-hosting, Buzz connection diagnostics, 버즈 커뮤니티 연결, Buzz 메시지 첨부."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: messaging-integration
    role: tracker
    quality_tier: evidence-gated
---

# Buzz

This is a Hermes-native `buzz` workflow skill.

## Why This Exists

Hermes already owns the Buzz transport, but users need one discoverable OMH entry point that safely selects setup, attachment, or self-host operations and reports only the evidence actually observed.

## Do Not Use When

- The user wants a Buzz-managed ACP runtime rather than Hermes' native Buzz gateway; say it is outside this skill.
- The request is general media editing with no Buzz delivery target.
- The request is generic Docker or Nostr advice unrelated to a Buzz relay.
- The user is only asking whether OMH supports Buzz, with no request to run the workflow.

## Examples

Good example:

- Prompt: Connect this Hermes gateway to my Buzz community and verify one inbound and outbound message.
- Expected behavior: Load the setup reference, collect the relay and membership inputs without exposing the private key, use Hermes' guided gateway setup, then report each observed verification stage.
- Why: The request names the native gateway task and an observable end-to-end stop condition.

Bad example:

- Prompt: Write a generic Nostr relay from scratch for OMH.
- Expected behavior: Route to planning or coding rather than presenting that transport as part of omh-buzz.
- Why: OMH reuses Hermes' native Buzz adapter and does not own a second Nostr transport.

## Completion Checklist

- Exactly one of setup, media, or self-host is selected from request meaning; no internal lane is public.
- Secrets remain out of argv, logs, rendered output, and workflow artifacts.
- Configuration, process, relay, event acceptance, subscription, and client rendering are separate claims.
- Any state-changing self-host command remains user-driven and has an explicit rollback or backup boundary.
- The final answer names what was observed, what remains unobserved, and the next smallest proof action.

## Recovery Notes

- If the Buzz CLI is missing, stop at installation guidance and do not claim gateway readiness.
- If relay authentication fails, separate membership, identity, and NIP-42 evidence before changing config.
- If a send receipt is malformed or lacks an event id, report ambiguous delivery and do not auto-retry.
- If self-host readiness is green but media fails, inspect MinIO and disk separately from relay readiness.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Choose One Internal Lane

`omh-buzz` is the only public skill. Choose exactly one reference from the
request's meaning after this skill is selected:

- Load `references/setup.md` to connect or repair Hermes' native Buzz gateway.
- Load `references/media.md` to deliver a local attachment to the active Buzz
  conversation and report staged delivery evidence.
- Load `references/self-host.md` to inspect or guide a self-hosted Buzz relay.

Do not expose these references as separate skills and do not select them with
a hard-coded keyword branch. If the request genuinely spans lanes, start with
setup/readiness, then load only the next reference required by observed state.

## Ownership Boundary

Hermes owns the native Buzz transport, authentication, inbound subscriptions,
and outbound CLI invocation. OMH owns this operator workflow, the `buzz`
platform identity layered over source `hermes`, safe evidence boundaries, and
progressive guidance. Block's Buzz relay and CLI own their runtime semantics.

## When to Use

Use when the user wants to configure or troubleshoot Hermes' native Buzz gateway, attach local media to the active Buzz conversation, or inspect a self-hosted Buzz relay. Select the setup, media, or self-host reference from the request's meaning after this single public skill is selected.

    Strong routing signals: `connect Hermes to Buzz`, `Buzz community agent`, `Buzz gateway setup`, `Buzz media attachment`, `Buzz relay self-hosting`, `Buzz connection diagnostics`, `버즈 커뮤니티 연결`, `Buzz 메시지 첨부`

## Catalog Metadata

Category: `operator`
Phase: `messaging-integration`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Name the workflow target, constraints, validation evidence, and stop condition.
- Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.

Handoff policy:

Operate through Hermes' native Buzz adapter and official Buzz surfaces. Keep state-changing self-host commands user-driven and delegate repository code changes only when the user explicitly asks for them.

Required inputs:

- Buzz task: gateway setup, media delivery, or self-host diagnosis
- target Hermes home or active Buzz conversation
- observable stop condition

Expected outputs:

- selected Buzz workflow lane
- bounded setup or diagnostic evidence
- observed delivery stage or explicit unobserved boundary

Artifact expectations:

- redacted Buzz readiness summary when setup is inspected
- delivery receipt with accepted event id when media is sent
- self-host failure-tree evidence when relay health is diagnosed

Safety rules:

- Reuse Hermes' native Buzz transport; do not implement or imply an OMH-owned Nostr transport.
- Never print, persist in workflow artifacts, or place the Buzz private key in argv or shell history.
- Do not treat CLI presence, configuration presence, or a prepared command as live relay readiness.
- Do not claim message delivery without accepted=true and a non-empty event id from the send receipt.
- Guide, don't drive state-changing self-host operations unless the user explicitly approves each action.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
