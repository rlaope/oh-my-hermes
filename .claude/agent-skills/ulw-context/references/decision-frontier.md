# Dependency-Ready Decision Frontier

Load this reference only when terminology correction exposes unresolved product or workflow decisions. A safe lookup does not enter this interview.

## Entry

Ask for explicit confirmation before starting. First inspect repository and source evidence for facts Hermes can discover. The user owns product decisions; do not ask them to retrieve facts available locally.

## Dependency Model

Represent each unresolved decision with its prerequisites and dependents. Assign append-only `D1`, `D2`, ... identifiers and never renumber or reuse them. A decision is `open`, `resolved`, `deferred`, `blocked`; reachability is separate from state.

In each round, present the whole dependency-ready frontier: every reachable open decision whose prerequisites are resolved. One emitted batch consumes one round regardless of item count. Do not ask a dependent question in the same round as its prerequisite.

Open each batch with `Frontier round {n}/6 · Resolved {r} · Deferred {d} · Blocked {b} · Open {o}`. Find the latest header in the thread before incrementing it. Repository research, entry consent, the pre-Round-4 consent check, summary confirmation, and next-path consent consume no rounds.

For each frontier item:

1. state the decision and why it changes shared understanding;
2. summarize observed evidence and unknowns;
3. give one concise recommendation with the main tradeoff;
4. ask for the user's decision, correction, or skip.

Apply unambiguous answers only to the identifiers they address. Omitted decisions remain open. A recommendation becomes selected terminology only when the user explicitly accepts it. Apply addressed answers before evaluating a global stop request; newly unlocked dependents wait for the next round.

Record agreed canonical identity and short definition separately from design rationale. Keep rare, hard-to-reverse tradeoffs as decision notes rather than glossary entries.

## Stop and Transition

After each answer, stop on the first matching condition:

1. every reachable decision is resolved, explicitly deferred, or blocked by named missing evidence;
2. the user asks to stop questioning or proceed;
3. the answer to Round 6 was recorded.

On user stop or budget exhaustion, keep unaddressed decisions open and show recommendations only as proposed assumptions. Never emit Round 7. Read back resolved, deferred, blocked, and open decisions separately and ask the user to confirm that summary. Confirmation closes the interview; it does not approve implementation.

If no valid round header or decision identity survives context compaction, do not restart or emit another decision round. Summarize only recoverable decisions and close unresolved items with a named `compaction_state_unavailable` blocker.

After confirmation, offer either `ulw-plan` for a reviewed implementation plan or a selected executor-neutral coding-owner handoff when work is already plan-ready. Ask for a separate go-ahead before preparing either. A prepared handoff is not dispatch, execution, review, CI, merge-readiness, merge, or proof that the recipient used the terminology.

## Attribution

The dependency tree, frontier rounds, recommendation pattern, fact/decision split, and shared-understanding stop condition adapt ideas from Matt Pocock's `grilling` skill at `mattpocock/skills@84fdeffd12f2ee307994d1eb6feb48173b6e0502`, MIT License, Copyright 2026 Matt Pocock. OMH keeps planning and executor handoff as separate confirmed phases.
