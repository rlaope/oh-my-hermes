# Direction

## Product Thesis

OMH is a Hermes-native wrapper orchestration layer.

It should make Hermes feel mature in chat surfaces without pretending Hermes is
the main coding executor. The product is not a clone of a Codex-side workflow
runtime. It borrows the discipline of staged workflows, local state, and
evidence gates, then translates that discipline into Hermes-native chat,
planning, status, and handoff contracts.

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
- clearer wrapper response states and actions
- stronger prepared handoff payloads for coding executors
- stricter evidence boundaries for dispatch, execution, review, CI, and merge
- documentation and tests that keep public claims aligned with code

The goal is parity of seriousness, not parity of implementation shape.

## Project Type

OMH is:

- a Hermes-native skill pack with a tap-compatible `skills/` layout
- a local bootstrap and maintenance tool for managed Hermes skills
- a deterministic skill catalog and router contract
- a wrapper-native chat contract for Discord, Slack, and hosted adapters
- a Hermes-facing planning artifact generator
- a metadata-only evidence ledger for prepared and observed handoffs
- a delegation-first bridge from Hermes requests to selected coding executors

OMH is not:

- a Hermes core patch
- a Discord or Slack bot implementation
- an LLM router or network service
- a hidden coding runtime
- a claim that Hermes executed work that only a handoff prepared

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

Selected coding executors own:

- main implementation work
- code changes
- code review fixes
- verification execution
- merge-readiness work

## Direction Rules

1. Keep users command-agnostic in chat.
   Discord, Slack, and hosted wrappers should accept natural language and render
   skill, plan, status, and handoff UX without requiring users to know OMH
   commands.

2. Preserve prepared versus observed boundaries.
   `prepared_not_observed` means a handoff exists. It does not mean execution,
   review, CI, merge readiness, or merge happened.

3. Keep Hermes retained work high quality.
   Deep interview, source-backed research, planning, status narration, and
   evidence synthesis should improve inside Hermes-facing surfaces.

4. Delegate main coding deliberately.
   Coding-heavy work should ask for or apply an executor profile, then become a
   prepared handoff with scope, non-goals, acceptance criteria, verification
   expectations, and review expectations. Codex can use the run-backed
   lifecycle path in Phase 1; other profiles remain prompt-only until their
   lifecycle contracts exist.

5. Prefer local deterministic artifacts over hidden magic.
   Runtime records, wrapper sessions, and plans should be inspectable,
   schema-versioned, redacted by default, and local-only unless a wrapper
   outside this repository performs transport work.

   Memory/context review follows the same rule. OMH may inspect OMH-local
   memory files, wrapper sessions, target topology, setup profiles, and
   wrapper-supplied snapshots; it must not claim it read or changed opaque
   Hermes internal memory.

6. Do not widen into platform transports prematurely.
   Transport adapters, auth, retries, message edits, and posting belong outside
   this repository until their dependency and packaging story is explicitly
   approved.

7. Treat compatibility skill names as UX affordances.
   Workflow names may remain installed for familiarity, but their generated
   role and handoff policies must describe the Hermes-native boundary rather
   than implying copied runtime behavior.

## Delivery Grain

One user goal should normally produce one PR.

Inside that PR, multiple focused commits are fine: plan/documentation, tests,
implementation, review fixes, and CI fixes can all live in the same goal PR.
Do not split review feedback, follow-up test fixes, or small documentation
adjustments into new PRs unless they are independently releasable goals or the
user explicitly asks for a separate PR.

Split into separate PRs only when:

- the next change has a different user-facing goal
- the work has independent release or rollback value
- the current PR would become too risky to review coherently
- a dependency or external decision blocks part of the work
- the user explicitly requests stacked or separate PRs

## Strategic Milestones

1. Direction lock.
   Keep this document, architecture docs, README, generated skills, examples,
   and tests aligned around delegation-first wrapper orchestration.

2. Wrapper-native UX depth.
   Expand golden JSON into adapter pseudocode examples for Discord and Slack
   actions, threads, buttons, and status updates without adding transport
   dependencies.

3. Evidence completeness.
   Keep review, CI, merge-readiness, and merge observation records strict at
   the run level while wrapper sessions remain chat continuity only.

4. Retained cognition quality.
   Improve Hermes-side research, deep interview, and planning skills so
   non-coding requests feel first-class rather than like coding handoff
   leftovers.

5. Adapter boundary readiness.
   Only after the local contract is stable, consider example shims or adapter
   packages that consume `chat_interaction/v1` without moving platform secrets
   or network behavior into core OMH.

6. Skill-first distribution.
   Lead with Hermes skill tap/install when the target Hermes environment
   supports it. Keep `omh setup` as the bootstrap, repair, validation, and
   wrapper/backend route that creates the same Hermes-visible skill state
   through generated managed skills and `skills.external_dirs`.

## First-PR Vertical Slice Rule

When a goal is broad, keep the PR coherent rather than artificially tiny. A good
first slice should carry one user-visible capability from contract to tests:

- document the desired chat or handoff behavior
- encode the deterministic schema or catalog metadata
- expose the Hermes skill, setup, or wrapper-facing surface
- record local metadata-only artifacts when needed
- add focused tests for the public contract
- update README/docs so the capability is discoverable

Do not split the docs, implementation, review fixes, and CI fixes for that same
goal into separate PRs unless one of the Delivery Grain split conditions applies.

## Review Checklist

Before accepting direction-changing work, verify:

- Does it keep Hermes as orchestrator and narrator, not hidden coder?
- Does it keep coding execution in a selected executor handoff when code
  changes are required?
- Does it preserve `prepared_not_observed` until wrapper evidence exists?
- Does it avoid Hermes core patching, LLM/API calls, and transport networking?
- Does it keep chat users free from command knowledge?
- Does it fit one coherent goal PR unless there is a clear reason to split?
