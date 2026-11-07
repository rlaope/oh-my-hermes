---
name: "dag-ulw"
description: "[omh] Large multi-part job to run on its own: plan it as a graph of small nodes, run the ready ones in parallel through Hermes' delegate_task, verify the goal with a separate node, and repair failed nodes before reporting. Use when the user says: dag-ulw, dag ulw, ulw dag, dag ultrawork, ultrawork dag, даг ультраворк, граф задач, задачи графом."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, agent-coordination]
    category: agent-coordination
    phase: dag-delivery
    role: tracker
    quality_tier: evidence-gated
    related_skills: [ulw-work, ulw-plan]
---

# Dag Ulw

This is a Hermes-native `dag-ulw` workflow skill.

## Why This Exists

`dag-ulw` exists so a big job runs end to end without the person driving it: the parent plans a graph OMH can validate and draw, runs the ready nodes in parallel on Hermes' own children, verifies the goal with a separate node, and repairs before it reports.

## First Steps

- Start at once; there is no plan approval. Write the goal criteria in one line.
- When the conversation holds a plan the user accepted (from `omh-plan`, `ulw-plan` or `omh-refactor-plan`), build the graph from it instead of re-planning: each task becomes a node with its id, depends_on and write scope, its done check goes into VERIFY and STOP WHEN, and its closing verification task becomes the `role: verify` node; plan only what it leaves open.
- Plan the graph and call `omh_dag action=define` with the complete run `goal` and each node's id, label, category, prompt, depends_on, write_scope and role (`build` by default; `baseline`, `verify`, `review`); fix every refusal and read the lint before going on. Never `delegate_task` before `define` returns its calls. The saved goal reaches every native task; local VERIFY does not replace goal acceptance.
- Keep the plan todo as the run's layers in ONE tool: `todo_list` when `todo_list` is in your tool list or tool_search finds it (OMH mirrors it), else `omh_todo`; an accepted plan stays in `omh_todo`. One item per layer, named for what it delivers, never a list of its nodes (the panel draws those); advance it as each layer settles.
- For each call `omh_dag` returns, run its route (`omh_delegate_route`, set or fallback as given), then `delegate_task` with the tasks unchanged; never more calls than it returned. A call whose route names a `backend` (Hermes' model_map or profile_routes) runs no route tool: its tasks already carry what that backend takes. Then end the turn with one status line; never wait or poll.
- On each completion read the node's handoff file and call `omh_dag action=settle` (accepted, failed, or blocked; a provider error is failed with provider_error). Dispatch what it returns in the same turn.
- When the run reports done, check each node against its SCOPE and the goal criteria: extend the run when work is missing, otherwise report.

## Do Not Use When

- One small change with one owner and one check: run it directly, or use `ulw-work` when the person named it.
- The plan itself is still undecided and needs a reviewed decision record first; use `ulw-plan`.
- Workers must talk to each other mid-run rather than hand off through files; use `ulw-work` coordinated lanes.
- The graph tool (omh_dag) is not in your tool list: say so and offer `ulw-work` for the same plan; do not simulate the graph in chat.

## Examples

Good example:

- Prompt: dag ulw: add the export API, its UI button and the docs page, then verify with the full test suite
- Expected behavior: Define four nodes (api, ui after api, docs after api, verify after all), dispatch api, settle from its handoff, dispatch ui and docs together, run the verification node, report with the run summary.
- Why: Three producers with one ordering edge and a shared verification fan-in is the shape the graph is for.

Bad example:

- Prompt: dag ulw fix the typo in README
- Expected behavior: Fix it directly; a one-node graph adds a tool round trip and a status line for nothing.
- Why: One bounded edit has no parallelism or ordering to plan.

## Completion Checklist

- The run was defined in `omh_dag` before the first dispatch, and every dispatched node was settled.
- No two concurrently runnable nodes shared a write scope without an edge.
- A separate verification node ran the real command after every producer.
- Every accepted node was checked against its SCOPE; repairs stayed within two cycles per node and extend rounds within two per run.
- The report names what is still open and includes the observed run summary or an explicit run-summary not_available line before any specific next-action question.

## Recovery Notes

- A node whose child returned blocked or failed blocks only its dependents: repair it, or report it.
- When `ready` returns no call because no slot is free, end the turn; the next completion frees one.
- When the conversation was compacted, `omh_dag action=status` still finds the run.

## Workflow Lane

- Current lane: **Intent -> plan** - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the request is a job of several parts that can run in parallel or in an order (a feature across modules, a migration, a broad cleanup, research then build then verify), or when the person says dag ulw.

    Strong routing signals: `dag-ulw`, `$dag-ulw`, `dag ulw`, `ulw dag`, `dag ultrawork`, `ultrawork dag`, `даг ультраворк`, `граф задач`, `задачи графом`

## Catalog Metadata

Category: `agent-coordination`
Phase: `dag-delivery`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- When adapting an existing capability, load `skill_view(name='omh-verification-gate', file_path='references/adaptation-quality.md')` before accepting a plan, dispatching work, or claiming completion; carry its criteria and comparisons into tasks and evidence.
- Split first: many small nodes beat one big one, but never split one shared write scope or one judgement.
- Climb the difficulty ladder `quick` -> `unspecified-low` -> `unspecified-high` with a one-line reason per climb; use `ultrabrain` at most once, and a graph whose every node is `deep` or `deep-work` is a routing failure. A `role=review` node takes category `review` where your routes serve it; a `role=baseline` node stays `quick` or `unspecified-low`; a `role=verify` node judges the run goal and baseline exemptions, so climb the ladder for it as for any judgement.
- Write every node prompt self-contained, in order: TASK, DELIVERABLE, SCOPE (what it may read and write), VERIFY (the literal command and expected result), STOP WHEN.
- `depends_on` only orders nodes; data moves through the handoff files `omh_dag` names, never through the parent's memory.
- Before full-suite verification, run a `baseline` node before changes and record in its handoff each failure's test id, assertion/error signature, command, environment and revision; make verification depend on it and exempt only those signatures re-executed under a comparable command at the pinned base and candidate revisions. Never exempt a changed same-id failure, missing evidence, skipped or reduced coverage, collection/exit errors, or security/mandatory gates; disclose genuine baseline failures as pre-existing rather than calling a full-suite-green goal met.
- End every run with a `role: verify` node that depends on every producer, runs the real command, and is never the node that built the work.
- Completion is a claim: report the goal met only when `omh_dag` says `verdict: verified`, and first check each node against its SCOPE in both directions, nothing owed missing and nothing beyond it done.
- Goal loop: verify, repair, extend, verify. A failed check gets repair nodes (`omh_dag action=repair`, two cycles per node, the last re-plans); when every node passed but the goal check finds work missing, add it to the same run (`omh_dag action=extend`, two rounds per run). Past either limit, report what is still open.
- Unknown path: scout first; see 'When the path is unknown' in `references/run-loop.md`.
- On a messenger, each completion turn's reply is the run's one status line, and dispatch goes one call per layer and category so the posts stay bounded; load `references/run-loop.md` for the messenger, repair, extend and export details.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval: the turn ends by naming that next action and asking whether to take it, as one question carrying the choices the user has, never by declaring what will not be done; persistence never broadens the authorized scope. A refused escalation is answered the same way, with a safer alternative inside the boundary or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences for a simple change. Lead with the result and validation; omit abandoned approaches unless they explain a tradeoff, and internal bookkeeping. Disclose requested-but-not-done work and material prepared/unmerged work; omit unrelated non-action footers. Required accounting stays outside this scaling. Order: result -> relevant evidence/limits -> observed accounting (when required) -> specific question (if useful). For a real unresolved user decision or a useful briefing discussion, offer one specific, content-linked question. Completed work needs no question; discussion grants no authority. Never estimate usage.
- Close a finished run with `omh_run_summary` and print its summary_text verbatim, or an explicit run-summary not_available line, before any specific next-action question -- never estimated numbers.

Handoff policy:

Hermes owns the plan, the dispatch, the settling and the verdict; every node runs as Hermes' own `delegate_task` child, routed per category with `omh_delegate_route`. OMH's `omh_dag` tool keeps the graph, and only its calls start nodes: a `delegate_task` without the `[dag:<run>/<node>]` marker it returned is no node of the run. Coding nodes go to an external coding CLI only when the person chose that owner within the last day (`omh chat`, `omh coding`, or naming it in a dag-ulw request); then `omh_dag` lists each owner's nodes under `exports`. Otherwise no external CLI runs.

Required inputs:

- the goal and the criteria that prove it
- the workspace the nodes may change

Expected outputs:

- `omh_dag/v1` run with nodes, edges and settled outcomes
- verification node result against the goal criteria
- closing report: what passed, what is still open, the run summary

Artifact expectations:

- `omh_dag/v1` record under the OMH home, one per run
- one handoff file per node, written by its child and read by the nodes after it

Safety rules:

- Two nodes that can run at the same time never share a write scope; a shared file needs an edge or one owner.
- A node's own report is a claim: settle it accepted only after reading its handoff file, and settle a child that says it is blocked as blocked.
- Ask the person only for scope, spend, or an irreversible step, as one required `Authorize` question; an unanswered question means that part does not start.
- No external coding CLI runs unless the person already chose it as the coding owner.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
