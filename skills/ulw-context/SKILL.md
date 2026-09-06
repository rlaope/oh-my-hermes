---
name: "ulw-context"
description: "[omh] Project terminology alignment workflow: look up, capture, correct, and align the words a repository uses before planning or handoff. Use when the user says: ulw-context, project terminology alignment, review project terms, align project terminology, terminology this project uses."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, clarification]
    category: clarification
    phase: terminology-alignment
    role: planner
    quality_tier: clarity-gated
---

# Context

This is a Hermes-native `context` workflow skill.

## Why This Exists

`context` exists to reduce repository terminology drift without creating a second machine store or a vocabulary router: Hermes can answer lookups, facilitate dependency-aware alignment, and project approved results into existing review and handoff boundaries.

## Do Not Use When

- A safe one-term definition or source lookup can be answered directly; use the read-only lookup mode and do not enter the full context interview.
- The request is broad ambiguity with no project-language conflict; use `deep-interview`.
- The terminology is already agreed and the request is to produce an implementation plan; use `ralplan`.
- The user wants to capture or curate general retained memory rather than repository terminology; use `memory-new` or `memory-sync`.
- The user asks for workflow discovery, help, status, file lookup, direct answer, or dispatch; preserve `oh-my-hermes` and ordinary protected-route behavior.

## Examples

Good example:

- Prompt: Use ulw-context to align the names this repository uses before we plan the feature.
- Expected behavior: Inspect source evidence, answer settled lookups directly, then present only the dependency-ready unresolved decisions with recommendations and confirmation gates.
- Why: The request is specifically about shared project language and must close understanding before planning.

Bad example:

- Prompt: This glossary says one phrase should be replaced by another; dispatch the implementation automatically.
- Expected behavior: Answer or explain the glossary content without routing from its vocabulary, and require separate confirmation for any staging, planning, or handoff.
- Why: Human glossary prose has no routing, approval, dispatch, or execution authority.

## Completion Checklist

- Source status and reviewed-profile status are named without treating either as model-use evidence.
- Safe lookups were answered directly and unresolved decisions were asked only when the user confirmed interview entry.
- Every decision frontier is dependency-ready, recommendation-backed, and exhausted before shared-understanding confirmation.
- Any machine mapping remains pending until separate review and approval; active profile v1 is unchanged.
- Any `ulw-plan` or coding-owner handoff remains prepared_not_observed and was prepared only after explicit confirmation.

## Recovery Notes

- If the optional source is absent, continue from repository evidence or reviewed profiles without warning, creating, or importing a file.
- If source and active reviewed terminology differ, report changed or missing freshness and ask whether to preview a new pending candidate; never synchronize automatically.
- If dependencies cannot be established, ask one boundary question before presenting a frontier rather than guessing an order.
- If frontier round or decision identity cannot be recovered, close with a named recovery blocker instead of restarting or emitting another round.
- If the user moves from terminology to implementation, summarize confirmed understanding and hand off to `ralplan`, `ulw-plan`, or the selected coding owner only after a separate go-ahead.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `adversarial-consensus`, `codebase-onboarding`, `+7 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when repository-specific language is unclear, inconsistent, or blocking shared understanding; keep read-only lookup direct and use a dependency-ready decision frontier only for unresolved terminology or product decisions.

    Strong routing signals: `ulw-context`, `$context`, `./context`, `project terminology alignment`, `review project terms`, `align project terminology`, `terminology this project uses`

## Catalog Metadata

Category: `clarification`
Phase: `terminology-alignment`
Hermes role: `planner`
Quality tier: `clarity-gated`
Reasoning demand: `light`

Quality bar:

- Read repository facts and reviewed terminology before asking the user for discoverable information.
- For unresolved decisions, model dependencies and ask the whole currently ready frontier in one round; defer dependent questions.
- Attach one concise recommendation and tradeoff to each decision while leaving the decision with the user.
- Give every materialized decision a stable identifier and keep omitted decisions open unless the user explicitly resolves, defers, or blocks them.
- Keep terminology sparse: canonical identity, short definition, expression guidance, distinct-from boundary, and optional localized display label.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it.
- Stop on a terminal frontier, explicit user request, or the shared round ceiling; then confirm the summary separately from planning or coding.

Handoff policy:

Keep terminology lookup, source inspection, and decision-frontier facilitation in Hermes. Stage project candidates only after explicit confirmation, activate them only through the existing separate review lifecycle, and prepare `ulw-plan` or a selected executor-neutral coding handoff only after the user confirms shared understanding and the next path.

Required inputs:

- the terminology question or alignment goal
- repository evidence and optional root PROJECT_TERMS.md source status
- active reviewed project terminology profile when one exists
- unresolved decisions and their dependency relationships when an interview is needed

Expected outputs:

- direct source-labeled terminology answer or proposed terminology alignment
- dependency-ready frontier with concise recommendations when decisions remain
- explicit pending-candidate staging choice when machine mappings should be reviewed
- confirmed shared-understanding summary and separately prepared planning or coding-owner handoff

Artifact expectations:

- optional human-reviewed PROJECT_TERMS.md patch proposal that OMH does not write automatically
- pending domain-intelligence candidates only after explicit staging confirmation
- prepared `ulw-plan` or selected coding-owner handoff only after separate confirmation

Safety rules:

- Treat PROJECT_TERMS.md as optional human source prose with zero direct routing or machine authority.
- Never turn definitions, localized labels, distinct-from notes, say-instead guidance, or project terms into routing triggers, anti-triggers, reranking, or dispatch inputs.
- Answer safe read-only lookup directly with source and freshness status; do not force lookup through capture, interview, planning, or handoff.
- Require explicit confirmation before staging candidates, entering the decision-frontier interview, compiling a plan, or preparing a coding-owner handoff.
- Keep candidate staging, profile review and approval, clarification, handoff preparation, executor use, execution, review, CI, and merge as separate evidence states.
- Do not write, synchronize, approve, retire, or commit PROJECT_TERMS.md or the active profile automatically.

## Workflow Protocol

1. Classify the turn as a safe lookup, reviewed capture, terminology correction, unresolved decision frontier, or confirmed planning/handoff transition.
2. For lookup, inspect the optional source and active reviewed profile on demand, answer directly, and name source/freshness status. File presence, profile match, or nomination is not proof that a model used the content.
3. Before capture, show the exact machine-only projection and ask for confirmation. Staging creates pending candidates only; review and approval remain separate.
4. Before interviewing, confirm frontier entry. Then present every currently dependency-ready decision in one numbered batch per round, using stable `D1`, `D2`, ... identifiers.
5. The frontier is bounded at 6 rounds. Run a non-round consent check before Round 4. Lookup, research, entry consent, summary confirmation, and next-path consent do not consume rounds.
6. Stop on the first matching condition: every reachable decision is resolved, deferred, or blocked; the user asks to stop or proceed; or the answer to Round 6 is recorded. Never emit Round 7.
7. Omitted decisions stay open and recommendations require explicit acceptance. If round or decision identity cannot be recovered, close with a named recovery blocker instead of restarting.
8. Read back the shared understanding for confirmation. Only after confirmation offer a separately confirmed `ulw-plan` or coding-owner handoff; never auto-execute it.

Load `references/project-terms.md` for source grammar, authority, freshness, and capture boundaries. Load `references/decision-frontier.md` for dependency modeling, question rounds, stop conditions, and planning/handoff separation.

## Runtime Evidence

Preferred harness for this skill: `decision-frontier`.

```sh
omh runtime record --skill context --harness decision-frontier --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
