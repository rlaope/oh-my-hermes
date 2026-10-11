# Dependency Topology Discipline

Load this reference before dispatch whenever an accepted `ultrawork` plan has more than one work unit. Resolve `dependency_topology` first; a prepared topology is still not dispatch, execution, verification, review, CI, or merge evidence.

## Topology Lock

Enumerate one to six top-level components that can independently succeed or fail before creating lanes. Every lane maps to exactly one component. Do not collapse distinct components into one vague lane, and do not invent components the request does not have.

Split first, route second. Prefer small, independently verifiable lanes when their read/write scopes are disjoint. Keep a coherent judgment or shared invariant under one owner when splitting would destroy the context needed to succeed.

## Shape Selection

- **One owner:** work coupled by a shared invariant or inseparable edit boundary.
- **Ordered dependency edges:** separable work whose downstream unit cannot start until named producers finish.
- **Dependency-ready parallel frontier:** independent units with disjoint write scopes.

Use a DAG only when ordering is the point. Two units with no dependency edge are plain parallel work, not a graph. For stage-shaped work, fan out producers and fan in through an explicit integration or synthesis unit. Use a live team only when workers must communicate during execution; ordering alone does not require a team.

## Edges and Matrix Check

A dependency edge (`dependsOn` or `depends_on` on the host) orders execution only. It never substitutes upstream output into a downstream prompt. Paste already-known facts into the prompt; use an edge only when the downstream unit consumes an upstream result.

Before dispatch, verify that every referenced id exists, no unit depends on itself, the graph is acyclic, every edge is necessary, and the initial frontier contains at least one runnable unit.

## Write Discipline

Every concurrently runnable unit declares exact read and write scopes and never overlaps another runnable unit's write scope. A shared file requires an ordering edge or one owner. One unit owns a deliverable end to end, including its proof; never split implementation and tests for the same files across concurrent owners.

If integration reveals an unexpected shared-file or shared-invariant conflict, stop the affected frontier and reassign ownership before more edits.

## Node Prompt Contract

Every lane prompt stands alone and contains, in order:

1. `TASK`: one imperative assignment.
2. `DELIVERABLE`: the exact artifact or result.
3. `SCOPE`: read/write boundaries and forbidden changes.
4. `VERIFY`: the literal command or action plus one binary pass/fail observable.
5. `STOP WHEN`: the observable state that ends the lane.

`DELIVERABLE` and `SCOPE` name exact paths. Use one role per node. A dependency edge only orders execution: it never stands in for an upstream lane's output, so a prompt restates whatever it needs from upstream. Missing markers, vague scopes, or non-binary verification are definition defects fixed before dispatch.

## Verification Fan-In

Every code-changing graph ends with a verification unit that depends on all producer units. It runs the repository's real test, build, or user-surface command and records captured pass/fail output. A downstream unit re-checks upstream claims against artifacts before trusting them.

## Recovery

Recover node-locally. A failed node blocks only its dependents. Read the failure, retry the node first, amend its prompt or definition when the contract was wrong, and steer an already-live worker instead of creating a duplicate owner. Do not rebuild the entire graph unless its definition is corrupt.

A quiet, queued, or scheduled node is not stalled. A returned blocked response is a completed node carrying a blocker; record it and keep dependents blocked.

## Host Capability

On a graph-capable host, encode real edges and dispatch the dependency-ready frontier. OMH's `fanout_contract/v2` is the reference behavior: unknown or cyclic dependencies fail, overlapping files without an edge fail, and admission advances as dependencies complete.

On a host without native DAG support, run edge-free units as plain parallel native subagents and run ordered units sequentially in topological order. This is a fallback inside `ulw-work`, not a separate skill or hidden runtime.
