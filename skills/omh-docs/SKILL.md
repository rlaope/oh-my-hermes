---
name: "omh-docs"
description: "[omh] Current-source-first documentation for OMH itself: product identity, public capability catalog, model routing, local state, and long-term memory. Use when the user says: product-docs, OMH documentation, oh-my-hermes documentation, what is OMH, what is oh-my-hermes, how does OMH work, OMH capability catalog, OMH skill catalog."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: product-documentation
    role: researcher
    quality_tier: source-gated
---

# OMH Docs

Use this skill to answer questions about OMH itself from current sources. It
defaults to passive inspection; it is not a generic documentation writer,
workflow picker, or settings workflow.

## Default Behavior

1. Classify the question as a public-product fact, a current-local-install
   fact, or both. Keep those claim sets separate in the answer.
2. Retrieve only the sources needed for the question. Current public facts must
   come from official `rlaope/oh-my-hermes` sources; current local facts must
   come from passive CLI output, or narrowly scoped non-secret metadata. If a
   diagnostic command records state, disclose that side effect before running it.
3. Disclose the source URL or command/path and the relevant ref, version, or
   commit. If freshness cannot be established or official sources conflict,
   name that boundary.
4. Answer the one-shot question directly. Do not create a durable artifact
   unless the user requests one.

For a public catalog count, inspect the generated catalog on the current
official ref. For an installed count, run `omh list --json` and count only that
installation manifest. Never quote a remembered or embedded count.

## Source Route

For public/product questions, start with live GitHub repository metadata and
the current default branch, then read the relevant current source. Load
`references/product-and-sources.md` for the full official-source hierarchy,
product identity, conflict handling, and disclosure shape.

For current capability and public skill-name questions, load
`references/capability-map.md`. It covers the six public capability families,
representative exact skill names, catalog retrieval, and the public ULW labels.

For model routing or this machine's installation, load
`references/model-routing-and-local-state.md`. It separates published routing
behavior from passive local inspection, the state-writing `omh doctor --json`
diagnostic, and safe inspection of the resolved OMH home (`~/.omh` by default,
but overridable).

For retained knowledge or memory questions, load
`references/long-term-memory.md`. It distinguishes reviewed OMH project memory
from Hermes private long-term memory and points to `docs/MEMORY.md` and
`docs/MEMORY_CONTEXT.md`.

## Public Product vs Local Install

- Public-product facts describe the current official repository at a disclosed
  branch, tag, version, or commit. A local checkout does not silently replace
  that source.
- Local-install facts describe only the inspected machine/profile at a
  disclosed OMH version or commit. Documented paths can be absent because
  install profiles and enabled features differ.
- When both matter, report them under separate labels before explaining any
  difference.

## Safety and Mutation Boundary

Never read or print credentials, tokens, auth files, `.env` values, provider
secrets, raw private logs, or unrelated user content. Do not broaden a metadata
question into a home-directory scan.

If the user asks to set up, install, update, repair, change settings, edit
memory, or modify code, name the appropriate specialized public workflow such
as `omh-doctor`, `omh-skill`, `omh-model-setup`, or `omh-memory-sync`, then stop
before mutation unless that separate action is authorized.

## Answer Contract

- Lead with the answer, then the public-product and local-install evidence that
  supports it.
- When both scopes matter, label the evidence `public_product` and
  `current_local_install` before explaining differences.
- Cite the exact official source or disclosed local observation used.
- State version, branch, tag, or commit and the retrieval boundary.
- Name missing or conflicting evidence instead of filling it from recall.
- Mention execution/review status boundaries only when the question actually
  asks about status; they are not the center of this documentation skill.

## Workflow Lane

- Current lane: **Research and company ops**. Stay read-only and return to the
  router when the request belongs to another workflow.
- Shared product, routing, compatibility, and evidence rules:
  `omh-routing/references/skill-common-rail.md`.

## Completion Checklist

- Answer only from disclosed current sources or bounded local observations.
- Treat wrapper metadata-only memory comparisons as advisory local context,
  not proof of Hermes-memory mutation or raw-entry exposure.
- Record observed delegation results; otherwise return `not_available` or
  `not_observed`.
- Prepared OMH routing is not execution, review, CI, or merge evidence.
- Preserve workflow intent and stop conditions; verify before claiming
  completion.
- Use Hermes-native subagent/delegation features when available:
  native subagents -> Hermes delegation when available, otherwise sequential lanes.

## Recovery Notes

- If official retrieval fails, disclose the gap and use only versioned fallback
  evidence.
- If local metadata is absent, report that scoped absence without expanding
  into private content or mutation.
