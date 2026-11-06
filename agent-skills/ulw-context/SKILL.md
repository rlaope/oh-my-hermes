---
name: "ulw-context"
description: "[omh] Repository vocabulary unclear or inconsistent: project terminology alignment workflow: look up, capture, correct, and align the words a repository uses before planning or handoff. Use when the user says: ulw-context, project terminology alignment, review project terms, align project terminology, terminology this project uses."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, clarification]
    category: clarification
    phase: terminology-alignment
    role: planner
    quality_tier: clarity-gated
---

# Context

This is an OMH `ulw-context` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ulw-context` exists to reduce repository terminology drift without creating a second machine store or a vocabulary router: the host can answer lookups, facilitate dependency-aware alignment, and project approved results into existing review and handoff boundaries.

## Do Not Use When

- A safe one-term definition or source lookup can be answered directly; use the read-only lookup mode and do not enter the full context interview.
- The request is broad ambiguity with no project-language conflict; use `ulw-interview`.
- The unresolved decision is empirical and a cheap isolated experiment can answer it; use `omh-decision-prototype` and keep the frontier for the rest.
- The terminology is already agreed and the request is to produce an implementation plan; use `ulw-plan`.
- The user wants to capture or curate general retained memory rather than repository terminology; use `omh-memory-new`.
- The user asks for workflow discovery, help, status, file lookup, direct answer, or dispatch.

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
- If the user moves from terminology to implementation, summarize confirmed understanding and hand off to `ulw-plan` or the selected coding owner only after a separate go-ahead.



## When to Use

Use when repository-specific language is unclear, inconsistent, or blocking shared understanding; keep read-only lookup direct and use a dependency-ready decision frontier only for unresolved terminology or product decisions.

    Strong routing signals: `ulw-context`, `$context`, `./context`, `project terminology alignment`, `review project terms`, `align project terminology`, `terminology this project uses`

## Catalog Metadata

Category: `clarification`
Phase: `terminology-alignment`
Quality tier: `clarity-gated`
Reasoning demand: `light`

Quality bar:

- Read repository facts and reviewed terminology before asking the user for discoverable information.
- For unresolved decisions, model dependencies and ask the whole currently ready frontier in one round; defer dependent questions.
- Attach one concise recommendation and tradeoff to each decision while leaving the decision with the user.
- Give every materialized decision a stable identifier and keep omitted decisions open unless the user explicitly resolves, defers, or blocks them.
- Keep terminology sparse: canonical identity, short definition, expression guidance, distinct-from boundary, and optional localized display label.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval: the turn ends by naming that next action and asking whether to take it, as one question carrying the choices the user has, never by declaring what will not be done; persistence never broadens the authorized scope. A refused escalation is answered the same way, with a safer alternative inside the boundary or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences for a simple change. Lead with the result and validation; omit abandoned approaches unless they explain a tradeoff, and internal bookkeeping. Disclose requested-but-not-done work and material prepared/unmerged work; omit unrelated non-action footers. Required accounting stays outside this scaling. Order: result -> relevant evidence/limits -> observed accounting (when required) -> specific question (if useful). For a real unresolved user decision or a useful briefing discussion, offer one specific, content-linked question. Completed work needs no question; discussion grants no authority. Never estimate usage.
- Stop on a terminal frontier, explicit user request, or the shared round ceiling; then confirm the summary separately from planning or coding.

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

- Optional human-reviewed PROJECT_TERMS.md patch proposal; never write it automatically.
- Pending domain-intelligence candidates only after explicit staging confirmation.
- Prepared ulw-plan or selected coding-owner handoff only after separate confirmation.
- Load references/project-terms.md for source authority and capture; load `references/decision-frontier.md` before interviewing for the dependency-ready batch protocol, stable decision IDs, round bounds, consent gates, and compaction recovery.

Safety rules:

- Treat PROJECT_TERMS.md as optional human source prose with zero direct routing or machine authority.
- Never turn definitions, localized labels, distinct-from notes, say-instead guidance, or project terms into routing triggers, anti-triggers, reranking, or dispatch inputs.
- Answer safe read-only lookup directly with source and freshness status; do not force lookup through capture, interview, planning, or handoff.
- Require explicit confirmation before staging candidates, entering the decision-frontier interview, compiling a plan, or preparing a coding-owner handoff.
- Keep candidate staging, profile review and approval, clarification, handoff preparation, executor use, execution, review, CI, and merge as separate evidence states.
- Do not write, synchronize, approve, retire, or commit PROJECT_TERMS.md or the active profile automatically.

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
