# Direction

## Product Thesis

OMH is a Hermes-native wrapper orchestration layer.

It should make Hermes feel mature in chat surfaces without pretending Hermes is
the main coding executor. The product is not a clone of a Codex-side workflow
runtime. It borrows the discipline of staged workflows, local state, and
evidence gates, then translates that discipline into Hermes-native chat,
planning, status, and handoff contracts.

The product should feel like a safe fit for an existing Hermes workflow, not a
separate CLI-first tool that users must learn before they get value. Assume many
users will skip most docs at first; the install path, first Hermes prompt,
status language, and repair commands must make the safe path obvious.

## Design Philosophy

Raise the product's capability level by strengthening contracts, not by hiding
more behavior behind prompts.

The desirable shape is a wrapper-native system where a user can type natural
language in Discord, Slack, or a hosted chat surface and receive a clear next
step: direct answer, clarification, research, plan, status, or coding handoff.
The user should not need to know command names, skill internals, or executor
syntax.

OMH should keep familiar workflow names only when they help users and wrappers
recognize intent. Those names are compatibility affordances, not permission to
copy another runtime's internals or imply hidden execution.

Quality should show up as:

- better request classification from local catalog metadata
- better Hermes-side interview, research, and planning output
- observation-first reporting that helps Hermes explain what happened after work
  starts or completes
- clearer wrapper response states and actions
- stronger prepared handoff payloads for coding executors
- stricter evidence boundaries for dispatch, execution, review, CI, and merge
- documentation and tests that keep public claims aligned with code

The goal is parity of seriousness, not parity of implementation shape.

## Command Audience

OMH is chat-first for people and command-addressable for agents. The normal
human shell surface is intentionally small:

- `omh setup` connects OMH to Hermes and repairs managed setup.
- `omh update` refreshes the command package and managed skills.
- `omh doctor` checks health and explains the next repair action.

After setup, the normal user workflow is to describe the desired result to
Hermes in natural language. Users should not have to translate coding,
research, memory, runtime, review, or release work into OMH subcommands.

The broader CLI is a deterministic control plane for Hermes Agent, wrappers,
coding agents, automations, and maintainers. Command groups such as `omh chat`,
`omh coding`, `omh runtime`, `omh memory`, `omh loop`, `omh goal`, `omh
harness`, `omh capabilities`, `omh release`, and `omh state` remain valuable
because agents can call, inspect, and compose them. They are not the default
human product surface.

Public documentation must preserve this audience boundary. Put setup, update,
doctor, and natural-language Hermes requests in user quick starts. Put other
commands under an explicit agent, wrapper, operator, maintainer, protocol, or
debugging label. A readable terminal command is not automatically a command
that normal users should learn.

## Observation-First Reporting

OMH should optimize for helping Hermes observe, summarize, and explain work,
not for exhaustively unifying every possible handoff order. Reverts and reruns
are often cheap. Losing the context of what Hermes invoked, what was observed,
what remains unobserved, and how to explain that to the user is more expensive.

The reporting direction is:

- structured state is the internal truth
- plain text is the default user experience
- markdown is a secondary durable knowledge surface
- workflow learning receives selected, sanitized summaries only

Structured summaries should be metadata-only by default. They can store schema
versions, work ids, workflow ids, message hashes and lengths, bounded evidence
references, progress events, observation refs, and claim boundaries. They must
not store raw prompts, raw platform events, raw logs, hidden reasoning, or
transcripts by default.

Hermes-facing progress, completion, and blocker updates should render as plain
language unless the user asks for JSON, schema output, debug data, or an API
payload. JSON/code-block output is an internal or opt-in surface, not normal
chat UX. The one exception, by owner decision (2026-10-20), is delegated work:
on a chat platform, the reply Hermes sends when a delegated run starts ends
with a short code block naming its tasks by layer, and the reply after it has
settled ends with a short block of how each task ended. In between, a reply on
a turn whose counts changed ends with one plain count line. The box drawing
stays in the OMH TUI and `omh hud --graph`, and nothing is a message of OMH's
own. `OMH_SUBAGENT_GRAPH=off` turns it off. See
[Seeing What Coding Work Is Running](CODING-OBSERVABILITY.md).

Internal awareness rails such as `[OMH Awareness]`, native bridge status
context, evidence-boundary reminders, process wrappers, and raw CI/watch
transcripts are inputs to reporting, not user-facing status copy. Adapters
should omit silent successful completions and summarize meaningful output into
the channel's natural voice. For example, Discord/Korean progress can use a
calm friendly voice while CI/DCO output becomes compact check status lines with
names, pass/pending/fail state, durations, and links instead of raw watcher
text.

Markdown export is useful for a wiki, notes, release recap, or later review,
but it is not a backend requirement for the current reporting contract. A
deterministic markdown projection from the structured summary is enough until a
real wiki store is intentionally designed.

Workflow learning should consume selected report summaries and bounded evidence
refs. It should not learn by dumping every chat message, executor log, or
private transcript into a learning artifact.

## Project Type

OMH is:

- a Hermes-native skill pack with a tap-compatible `skills/` layout
- a local bootstrap and maintenance tool for managed Hermes skills
- a deterministic skill catalog and router contract
- a wrapper-native chat contract for Discord, Slack, and hosted adapters
- a Hermes-facing planning artifact generator
- a metadata-only evidence ledger for prepared and observed handoffs
- a delegation-first bridge from Hermes requests to selected coding executors
- a terminal frontend over Hermes' own gateway (the OMH TUI bare `omh` opens),
  owning layout, input and the OMH panels while Hermes owns every model call,
  tool run, approval decision and `!` shell command the person types (it
  switches a session's model on its own only to follow a move of Hermes'
  configured default, at a turn boundary); its look
  is the rail and kind colours the owner picked on 2026-10-22 (a `┃` rail per
  transcript block with no fill, a call's state in its mark's glyph and colour
  as the dag view draws it, its name in its tool family's hue, the composer
  between two full-width rules with no side edges); in a dag run the agent
  view under the composer is a folding tree of the run's nodes, each with
  what its child is doing now

OMH is not:

- a Hermes core patch
- a Discord or Slack bot implementation
- an LLM router or network service
- a hidden coding runtime (the explicit, observed, opt-in exceptions are the
  fanout dispatch bridge and the Hermes-native child boundary: operator or
  maintainer commands that spawn local agent CLIs only after confirmation,
  isolate the process, and record authenticated observed evidence — the
  opposite of hidden; paired-run dispatch may compose the latter for
  digest-bound Hermes evaluation cells without adding a third process bridge)
- a claim that Hermes executed work that only a handoff prepared
- a replacement for Hermes' gateway, agent loop, or approval policy (the OMH
  TUI relays what the person types and answers no request on their behalf; a
  deny the person gives an approval also interrupts the running turn, as
  Claude Code's Esc does, except the deny from the row that tells Hermes what
  to do instead)

## Routing Language Policy

OMH targets a global audience with English as the primary language. Its
deterministic trigger tables, however, grew unevenly: Latin dominates the
catalog's routing triggers, Hangul is the next largest by a wide margin, the
shipped `ja` and `zh` trigger packs put Han and Kana behind it, and Devanagari,
Arabic, and Cyrillic have none at all. Chat copy is a separate surface --
`src/wrapper/localized_copy.py` renders it, and `SUPPORTED_COPY_LOCALES` covers
six non-English locales including Spanish, French, and German, which no trigger
pack recognises. (`src/routing/localization.py` is input-side folding --
normalization, tokens, and locale aliases -- and renders no copy at all.) OMH
therefore answers in more languages than its router recognises, and that
asymmetry is what the policy below is about.

Per-language trigger tables are not the fix. Matching the Korean table for one
more language means hundreds of hand-maintained entries, the work is unbounded
across the languages a global product must serve, and precision decays as the
catalog grows because more tokens mean more cross-skill collisions.

The policy:

- English is the primary trigger surface and stays the precision target.
- The existing Korean table is frozen, not extended. `tests/test_routing_language_policy.py`
  holds the count so growing it is a deliberate act with a visible number to
  change, and a non-English routing miss is never fixed by adding tokens.
- Input script is an explicit routing input, not an implicit accident.
  `src/routing/input_language.py` classifies it and states whether the trigger
  tables carry that script, so a zero score on a Hindi or Arabic request reads
  as missing coverage rather than missing intent. Japanese and Chinese left that
  category when their packs shipped.
- Non-English intent resolution belongs to model selection. Hermes already
  understands every language OMH would target; OMH supplies candidates,
  reasons, and evidence boundaries and lets the model choose.
- The candidates are supplied as a typed question, and an answer to it is
  recorded rather than acted on. An undecidable route carries `route_question`:
  one relative Choice over the shortlist plus `none`, and one absolute yes/no
  per candidate. `omh_route_answer` records an answer as
  `route_question_answer/v1` so it can be scored against OMH's own routing
  corpora. An unanswered question changes nothing and an answered one does not
  re-route anything: the deterministic route stays in force either way, and
  OMH names who answered rather than how good the answer was.

This keeps the "not an LLM router" boundary above intact: the selection happens
in Hermes, and core `omh` still makes no LLM, API, or network call on its own.
Two scoped exceptions reach the network. The opt-in `omh_jev_ask` tool: when
the user names Jev in a turn and a key resolves, it sends that turn's typed
questions to Jev and returns probabilities. It re-routes nothing; its answer
can be recorded with `answered_by: omh_jev_ask` only for an ask that OMH
process itself sent and Jev answered. And the OMH TUI's update notice, which
reads npm's latest published version at most once a day and names a newer
one; it sends nothing about the person, routes nothing, and is off with
`OMH_TUI_UPDATE_CHECK=0`, `omh theme update-check off`, or `omh update-check`
set to `off`. (The OMH TUI's gateway child is not core `omh`: it runs on
Hermes' interpreter and reaches the person's own Hermes gateway over loopback,
as Hermes' own TUI does, relaying that terminal's frames.)

## Project Terms Authority

A repository may carry an optional root-level `PROJECT_TERMS.md` as a portable,
human-reviewed source for project terminology. Its absence is a clean no-op:
setup and health checks must not create it, import it, or warn about it. The
file is project-scoped and has no direct machine authority. Editing, reviewing,
or committing it does not change routing or activate terminology in OMH.

Machine-readable terminology continues to use the existing reviewed
`domain_intelligence_profile/v1` lifecycle. A strict file preview may project
only phrase-to-canonical mappings and existing catalog workflow hints. Explicit
staging creates pending candidates only; a separate review and approval is
required before a profile becomes active. Human definitions, localized labels,
`distinct-from` notes, and `say-instead` guidance remain source prose and never
enter the profile. The profile schema, digest, and claim boundary remain
unchanged.

An active reviewed mapping is advisory clarification context, not authority.
The ordinary router decides first; project terminology may clarify only an
otherwise unresolved, router-owned interaction. A file, mapping, workflow hint,
or freshness result must never select or rerank a route, dispatch or execute
work, perform review or testing, run CI, approve a plan, merge code, or prove
that Hermes, a model, provider, or selected coding owner used the context.
Freshness is derived only during explicit project-scoped inspection and is not
persisted; source edits or deletion do not synchronize, replace, approve, or
retire a profile.

The generated `ulw-context` workflow is the public Hermes surface for safe
terminology lookup, explicitly confirmed reviewed capture, and dependency-ready
frontier interviewing. Its canonical catalog id is `context`. Generated name
and description metadata make it eligible for host semantic nomination, but
live Hermes semantic nomination is `not_tested`.
Current selection evidence is limited to explicit workflow invocation and a
deterministic lexical proxy over catalog metadata. That proxy measures lexical
competition; it is not evidence of semantic nomination by Hermes. Deterministic
OMH routing remains limited to explicit workflow invocation and catalog cues,
and the workflow adds no project-term, glossary, or per-language routing table.

Reviewed active project-domain mappings now reach coding handoffs through the
existing bounded context-pack lane. OMH resolves them read-only from its own
validated store and includes only approved summaries for the current project;
pending, rejected, retired, malformed, review-mismatched, digest-mismatched,
and scope-mismatched artifacts remain excluded. The same projection is used
for Codex, Claude Code, Hermes, and generic executor role packs. These packs are
prepared context only, not evidence that an executor or model received, read,
or used a mapping, and not dispatch, execution, review, CI, merge-readiness, or
merge evidence.

Exact `PROJECT_TERMS.md` bytes can reach a selected coding owner only through
explicit workspace-relative file selection in `handoff_input_manifest/v1`,
subject to content hashing, safety classification, item limits, and byte-budget
checks. They are not copied into every session, runtime record, or handoff
automatically. Manifest preparation or inclusion is likewise prepared context,
not proof of dispatch, receipt, reading, model use, execution, review, CI,
merge-readiness, or merge.

This direction adapts the dependency-frontier and terminology-separation ideas
from Matt Pocock's `grilling` and `domain-modeling` skills at revision
`84fdeffd12f2ee307994d1eb6feb48173b6e0502`, used under the MIT License
(Copyright 2026 Matt Pocock). It does not copy the upstream wrapper or make its
runtime behavior part of OMH.

## Ownership Boundary

Hermes owns:

- chat intake
- clarification
- source-backed research
- planning
- skill and workflow narration
- user-facing status continuity

OMH owns:

- deterministic local contracts
- generated Hermes skill content
- metadata-only runtime artifacts
- wrapper session state
- prepared coding handoff payloads
- derived status that separates prepared intent from observed evidence

Selected coding executors/runtimes own:

- main implementation work
- code changes
- code review fixes
- verification execution
- merge-readiness work

## Direction Rules

1. Keep users command-agnostic in chat.
   Discord, Slack, and hosted wrappers should accept natural language and render
   skill, plan, status, and handoff UX without requiring users to know OMH
   commands. Human-facing setup documentation should normally stop at `omh
   setup`, `omh update`, and `omh doctor`; broader command examples belong to
   clearly labeled agent or operator references.

2. Preserve prepared versus observed boundaries.
   `prepared_not_observed` means a handoff exists. It does not mean execution,
   review, CI, merge readiness, or merge happened.

3. Keep Hermes retained work high quality.
   Deep interview, source-backed research, planning, status narration, and
   evidence synthesis should improve inside Hermes-facing surfaces.

4. Delegate main coding deliberately.
   Coding-heavy work should ask for or apply an executor/runtime profile, then
   become a prepared handoff with scope, non-goals, acceptance criteria,
   verification expectations, review expectations, and a deterministic
   executor-prompt contract. That contract must tell the selected executor to
   inspect repository facts first, handle material uncertainty explicitly,
   report progress and blockers, and send only a bounded delta when an active
   turn needs steering. Codex can use the
   run-backed lifecycle path. Claude Code and generic agents can use portable
   prompt handoffs. Hermes, OMX, the pi-family runtime, and OMC can use
   `coding_runtime_handoff/v1`
   contracts with team/swarm, worker-protocol, and worktree guidance while still
   preserving prepared-vs-observed boundaries. Coding handoffs should also
   carry `worktree_session_isolation/v1` so wrappers know whether to continue in
   the same workspace, recommend a worktree, or require a worktree before
   opening the selected coding agent.

5. Prefer local deterministic artifacts over hidden magic.
   Runtime records, wrapper sessions, and plans should be inspectable,
   schema-versioned, redacted by default, and local-first.

   Memory/context review follows the same rule. OMH may inspect OMH-local
   memory files, wrapper sessions, target topology, setup profiles, and
   wrapper-supplied snapshots; it must not claim it read or changed opaque
   Hermes internal memory.

6. Keep Hermes Agent as the chat surface.
   OMH should not describe missing Discord/Slack bot layers as product gaps.
   The product story is that Hermes Agent receives natural language and consumes
   OMH skills, workflows, and local status contracts.

7. Treat compatibility skill names as UX affordances.
   Workflow names may remain installed for familiarity, but their generated
   role and handoff policies must describe the Hermes-native boundary rather
   than implying copied runtime behavior.

## Delivery Grain

One user goal should normally produce one PR. It carries the capability from
contract to tests. When a split is allowed, and how to report one, is
`AGENTS.md` (Delivery Grain); this page does not repeat it.

## Strategic Themes

Unordered themes, not a plan: none has an owner or a status.

- Direction lock.
  Keep this document, architecture docs, README, generated skills, examples,
  and tests aligned around delegation-first wrapper orchestration.

- Hermes-native UX depth.
  Expand golden JSON into Hermes Agent-facing examples for actions, threads,
  buttons, and status updates without turning them into separate bot products.

- Evidence completeness.
  Keep review, CI, merge-readiness, and merge observation records strict at
  the run level while wrapper sessions remain chat continuity only.

- Retained cognition quality.
  Improve Hermes-side research, deep interview, and planning skills so
  non-coding requests feel first-class rather than like coding handoff
  leftovers.

- Hermes surface readiness.
  Keep improving examples that consume `chat_interaction/v1` from the Hermes
  Agent side so users understand the chat-first flow without learning CLI
  commands.

- Skill-first distribution.
  Lead with Hermes skill tap/install when the target Hermes environment
  supports it. Keep `omh setup` as the bootstrap, repair, validation, and
  wrapper/backend route that creates the same Hermes-visible skill state
  through generated managed skills and `skills.external_dirs`.

## Review Checklist

Before accepting direction-changing work, verify:

- Does it keep Hermes as orchestrator and narrator, not hidden coder?
- Does it keep coding execution in a selected executor/runtime handoff when code
  changes are required?
- Does it preserve `prepared_not_observed` until wrapper evidence exists?
- Does it avoid Hermes core patching and hidden LLM/API calls?
- Does it keep chat users free from command knowledge?
- Does it fit one coherent goal PR unless there is a clear reason to split?
