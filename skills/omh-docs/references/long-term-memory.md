# Long-term Memory

Load this reference for questions about what OMH remembers, how reviewed
project context differs from Hermes memory, and which read-only sources explain
the current design.

## Two Memory Boundaries

- OMH project memory is reviewed, project-scoped context under `.omh/memory/`.
  Candidates remain separate from approved records; recall is bounded and
  source-labeled.
- Hermes long-term memory belongs to Hermes Agent. The bridge in
  `src/plugin_bundle/omh/hermes_memory.py` may read Hermes `MEMORY.md`,
  `USER.md`, memory-limit configuration, and approved OMH records to produce a
  metadata-only comparison. It cannot mutate Hermes memory.

The docs skill must not inspect or print raw Hermes memory merely because the
question mentions memory. Prefer the bridge's metadata-only summary; inspect
raw entries only when the user's narrowly scoped request and authorization make
that necessary.

An installed profile may also expose OMH-owned memory or learning metadata
under its resolved OMH home. Its presence and shape vary by version/profile and
do not prove that Hermes or a coding owner used the content.

## Current Sources

Read `docs/MEMORY.md` for reviewed project-memory lifecycle and
`docs/MEMORY_CONTEXT.md` for context admission, replay, and handoff boundaries.
Use `omh memory --help` and narrowly targeted read-only memory inspection
commands to confirm what the current installed CLI exposes. Disclose the
official ref and the local version or commit separately.

## Public Workflows

- `omh-memory-new` prepares a bounded new-memory candidate.
- `omh-memory-sync` reviews existing retained memory and proposed changes.
- `omh-decision-recall` retrieves reviewed rejected-decision context.
- `omh-wiki` organizes durable project knowledge.

These names identify specialized workflows; this docs skill only explains
them. If the user asks to capture, approve, retire, restore, prune, synchronize,
or otherwise mutate memory, route to the matching public workflow and stop
before mutation unless separately authorized.

## Privacy

Never answer a memory question by printing raw private logs, prompts,
transcripts, credentials, tokens, auth files, `.env` values, provider secrets,
or unrelated user content. Prefer schema, lifecycle, count, status, and
source-reference metadata over raw content.
