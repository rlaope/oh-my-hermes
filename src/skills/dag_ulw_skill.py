"""Canonical `dag-ulw` skill data: big multi-part work run as a graph of small nodes.

Pure catalog data. The parent Hermes agent plans the graph, the `omh_dag`
plugin tool keeps it (validation, readiness, settled outcomes), and every node
runs as Hermes' own `delegate_task` child. Nothing here executes.

The body is deliberately small: the run loop and the doctrine a planner needs
while writing nodes. Messenger behaviour, repair and extend, and the
external-owner export live in `references/run-loop.md`, read when they apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..plugin_bundle.omh.native_tools import NATIVE_TODO_TOOL, native_tool_presence_clause
from .catalog_types import (
    ADAPTATION_QUALITY_READ_RULE,
    ENGINE_CLOSING_BRIEF_RULE,
    ENGINE_FOLLOW_UP_AUTHORITY_RULE,
    ENGINE_INTERJECTION_RESUME_RULE,
    SkillDefinition,
    SkillExample,
)

if TYPE_CHECKING:
    from .render import SkillReferenceTemplate

DAG_ULW_RUN_LOOP_REFERENCE = "references/run-loop.md"

DEFINITION = SkillDefinition(
    "dag-ulw",
    "Large multi-part job to run on its own: plan it as a graph of small nodes, run the ready ones in parallel "
    "through Hermes' delegate_task, verify the goal with a separate node, and repair failed nodes before reporting.",
    (
        "dag-ulw",
        "$dag-ulw",
        "dag ulw",
        "ulw dag",
        "dag ultrawork",
        "ultrawork dag",
    ),
    "Use when the request is a job of several parts that can run in parallel or in an order (a feature across "
    "modules, a migration, a broad cleanup, research then build then verify), or when the person says dag ulw.",
    category="agent-coordination",
    phase="dag-delivery",
    hermes_role="tracker",
    handoff_policy=(
        "Hermes owns the plan, the dispatch, the settling and the verdict; every node runs as Hermes' own "
        "`delegate_task` child, routed per category with `omh_delegate_route`. OMH's `omh_dag` tool keeps the "
        "graph, and only its calls start nodes: a `delegate_task` without the `[dag:<run>/<node>]` marker it "
        "returned is no node of the run. Coding nodes go to an external coding CLI only when the person chose "
        "that owner within "
        "the last day through `omh chat` or `omh coding` (Hermes chat records no choice); then `omh_dag` "
        "lists them under `export`. Otherwise no external CLI runs."
    ),
    required_inputs=(
        "the goal and the criteria that prove it",
        "the workspace the nodes may change",
    ),
    expected_outputs=(
        "`omh_dag/v1` run with nodes, edges and settled outcomes",
        "verification node result against the goal criteria",
        "closing report: what passed, what is still open, the run summary",
    ),
    artifact_expectations=(
        "`omh_dag/v1` record under the OMH home, one per run",
        "one handoff file per node, written by its child and read by the nodes after it",
    ),
    safety_rules=(
        "Two nodes that can run at the same time never share a write scope; a shared file needs an edge or one owner.",
        "A node's own report is a claim: settle it accepted only after reading its handoff file, and settle a child "
        "that says it is blocked as blocked.",
        "Ask the person only for scope, spend, or an irreversible step, as one required `Authorize` question; "
        "an unanswered question means that part does not start.",
        "No external coding CLI runs unless the person already chose it as the coding owner.",
    ),
    quality_tier="evidence-gated",
    quality_bar=(
        ADAPTATION_QUALITY_READ_RULE,
        "Split first: many small nodes beat one big one, but never split one shared write scope or one judgement.",
        "Climb the difficulty ladder `quick` -> `unspecified-low` -> `unspecified-high` with a one-line reason per "
        "climb; use `ultrabrain` at most once, and a graph whose every node is `deep` or `deep-work` is a routing "
        "failure.",
        "Write every node prompt self-contained, in order: TASK, DELIVERABLE, SCOPE (what it may read and write), "
        "VERIFY (the literal command and expected result), STOP WHEN.",
        "`depends_on` only orders nodes; data moves through the handoff files `omh_dag` names, never through "
        "the parent's memory.",
        "Before full-suite verification, run a `baseline` node before changes and record in its handoff each "
        "failure's test id, assertion/error signature, command, environment and revision; make verification depend on "
        "it and exempt only those signatures re-executed under a comparable command at the pinned base and candidate "
        "revisions. Never exempt a changed same-id failure, missing evidence, skipped or reduced coverage, "
        "collection/exit errors, or security/mandatory gates; disclose genuine baseline failures as pre-existing "
        "rather than calling a full-suite-green goal met.",
        "End every run with a `role: verify` node that depends on every producer, runs the real command, and is "
        "never the node that built the work.",
        "Completion is a claim: report the goal met only when `omh_dag` says `verdict: verified`, and first check "
        "each node against its SCOPE in both directions, nothing owed missing and nothing beyond it done.",
        "Goal loop: verify, repair, extend, verify. A failed check gets repair nodes (`omh_dag action=repair`, two "
        "cycles per node, the last re-plans); when every node passed but the goal check finds work missing, add it to the same run "
        "(`omh_dag action=extend`, two rounds per run). Past either limit, report what is still open.",
        f"Unknown path: scout first; see 'When the path is unknown' in `{DAG_ULW_RUN_LOOP_REFERENCE}`.",
        "On a messenger, each completion turn's reply is the run's one status line, and dispatch goes one call "
        "per layer and category so the posts stay bounded; load "
        f"`{DAG_ULW_RUN_LOOP_REFERENCE}` for the messenger, repair, extend and export details.",
        ENGINE_INTERJECTION_RESUME_RULE,
        ENGINE_FOLLOW_UP_AUTHORITY_RULE,
        ENGINE_CLOSING_BRIEF_RULE,
        "Close a finished run with `omh_run_summary` and print its summary_text verbatim, or an explicit "
        "run-summary not_available line, before any specific next-action question -- never estimated numbers.",
    ),
    why_this_exists=(
        "`dag-ulw` exists so a big job runs end to end without the person driving it: the parent plans a graph "
        "OMH can validate and draw, runs the ready nodes in parallel on Hermes' own children, verifies the goal "
        "with a separate node, and repairs before it reports."
    ),
    opening_steps=(
        "Start at once; there is no plan approval. Write the goal criteria in one line.",
        "When the conversation holds a plan the user accepted (from `plan`, `ralplan` or `refactor-plan`), build the graph "
        "from it instead of re-planning: each task becomes a node with its id, depends_on and write scope, its done check "
        "goes into VERIFY and STOP WHEN, and its closing verification task becomes the `role: verify` node; plan only what "
        "it leaves open.",
        "Plan the graph and call `omh_dag action=define` with the complete run `goal` and each node's id, label, category, prompt, "
        "depends_on, write_scope and role (`build` by default; `baseline`, `verify`, `review`); "
        "fix every refusal and read the lint before going on. Never `delegate_task` "
        "before `define` returns its calls. The saved goal reaches every native task; local VERIFY does not replace goal acceptance.",
        f"Keep the plan todo as the run's layers in ONE tool: `{NATIVE_TODO_TOOL}` when "
        f"{native_tool_presence_clause(NATIVE_TODO_TOOL, code=True)} (OMH mirrors it), else `omh_todo`. One item per "
        "layer, named for what it delivers, never a list of its nodes (the panel draws those); advance it as each "
        "layer settles.",
        "For each call `omh_dag` returns, run its route (`omh_delegate_route`, set or fallback as given), then "
        "`delegate_task` with the tasks unchanged; never more calls than it returned. A call whose route names a "
        "`backend` (Hermes' model_map or profile_routes) runs no route tool: its tasks already carry what that "
        "backend takes. Then end the turn with one status line; never wait or poll.",
        "On each completion read the node's handoff file and call `omh_dag action=settle` (accepted, failed, or "
        "blocked; a provider error is failed with provider_error). Dispatch what it returns in the same turn.",
        "When the run reports done, check each node against its SCOPE and the goal criteria: extend the run when "
        "work is missing, otherwise report.",
    ),
    do_not_use_when=(
        "One small change with one owner and one check: run it directly, or use `ultrawork` when the person "
        "named it.",
        "The plan itself is still undecided and needs a reviewed decision record first; use `ralplan`.",
        "Workers must talk to each other mid-run rather than hand off through files; use `ultrawork` coordinated "
        "lanes.",
    ),
    good_example=SkillExample(
        prompt="dag ulw: add the export API, its UI button and the docs page, then verify with the full test suite",
        expected="Define four nodes (api, ui after api, docs after api, verify after all), dispatch api, settle "
        "from its handoff, dispatch ui and docs together, run the verification node, report with the run summary.",
        why="Three producers with one ordering edge and a shared verification fan-in is the shape the graph is for.",
    ),
    bad_example=SkillExample(
        prompt="dag ulw fix the typo in README",
        expected="Fix it directly; a one-node graph adds a tool round trip and a status line for nothing.",
        why="One bounded edit has no parallelism or ordering to plan.",
    ),
    final_checklist=(
        "The run was defined in `omh_dag` before the first dispatch, and every dispatched node was settled.",
        "No two concurrently runnable nodes shared a write scope without an edge.",
        "A separate verification node ran the real command after every producer.",
        "Every accepted node was checked against its SCOPE; repairs stayed within two cycles per node and extend "
        "rounds within two per run.",
        "The report names what is still open and includes the observed run summary or an explicit "
        "run-summary not_available line before any specific next-action question.",
    ),
    recovery_notes=(
        "A node whose child returned blocked or failed blocks only its dependents: repair it, or report it.",
        "When `ready` returns no call because no slot is free, end the turn; the next completion frees one.",
        "When the conversation was compacted, `omh_dag action=status` still finds the run.",
    ),
    situations=(
        "big job in parallel parts",
        "feature across several modules",
        "migration in ordered steps",
        "research then build then verify",
        "run the whole thing end to end",
    ),
)


def dag_ulw_reference_templates() -> list[SkillReferenceTemplate]:
    from .render import SkillReferenceTemplate  # render imports the catalog this module is part of

    return [SkillReferenceTemplate("dag-ulw", DAG_ULW_RUN_LOOP_REFERENCE, run_loop_reference())]


def run_loop_reference() -> str:
    """`references/run-loop.md`: what the body points to for messengers, repair and the external-owner export."""
    return """# dag-ulw run loop

## The calls, in order

1. `omh_dag action=define run=<id> name=<short name> goal=<criteria> nodes=[...]`. A refusal names what to fix:
   a cycle, an unknown or self dependency, two nodes writing one path with no edge between them, more than
   48 nodes, an empty graph, a node whose prompt names none of TASK / DELIVERABLE / SCOPE / VERIFY /
   STOP WHEN, and in a finite one-shot session (`hermes chat -q`) more nodes than the budget REMAINING in
   this process: `delegation.oneshot_max_children` (default 2, 0 = unlimited; a value that is not a positive
   integer uses the default; interactive sessions are never capped) minus the children already delegated
   this run, including non-dag `delegate_task` calls. If the host's one-shot detector itself
   cannot be read, define is refused as `oneshot_detection_unavailable` rather than run uncapped;
   `ready`, `settle`, `repair` and `extend` refuse it the same way, and the record is untouched.
   The nodes share one worktree: dependents and the verify node read earlier nodes' edits from it. With
   Hermes' `delegation.worktree_isolation` on, each child would start from the last commit without them, so
   define is refused as `worktree_isolation_on`, and a run defined before it was turned on hands out no
   call while it is on. OMH never writes the setting: relay the say and ask the person to turn it off for
   this profile. A config that cannot be read counts as off.
   Each node's `role` says what it is for: `build` (the default), `baseline`, `verify` or `review`; any
   other role is refused. Only a `verify` node verifies the goal, and every other node with a `write_scope`
   is a producer it has to follow. A node with no role that writes files and whose label opens with a check
   word (Verify, Validate, Audit, QA, Review) is refused as `role_required`: send `role=verify` (or
   `review`), or `role=build` when it builds.
   Lint is advice: a partial prompt-marker set, no verification node, a producer the verification node does
   not depend on, a node with no role whose label reads like another (`role_guess:<id>=verify`: give it
   the role; until then it runs as a native build node), a build node whose `write_scope` holds anything
   but docs with no `review` node in the run (`no_review_node`: add a `role=review` node when the change
   warrants a separate review, otherwise go on), every node `deep`, more than one
   `ultrabrain`, and a graph of 5+ nodes whose critical path is at least 80% of it (`serial_graph`: split
   it into parallel lanes where the work allows).
2. The result carries `calls`. Each call is one category (and route: a node retried after a provider error
   goes in a call of its own): run its `route` with `omh_delegate_route` (`set`, or `fallback`), then one
   `delegate_task` with its `tasks` unchanged. The goal ends with `[dag:<run>/<node>]`; that marker is how
   OMH ties the child to its node. A node after a repaired one is told to read the repair's handoff files.
   When Hermes (0.22.5+) runs a delegation backend other than `default`, the route names that `backend`
   instead and no route tool runs. Under `model_map` each task carries the user's `option` for its category
   (a retry takes the category's next option; a category no option matches carries none and runs on the
   backend's default). Under `profile_routes` OMH picks no profile: the tasks go as they are. Views name the
   option Hermes reports the child ran on, and a lane keeps its category only when that is the option handed out.
3. `calls` never exceeds the free background slots (`slots.free`): a call past them would run blocking.
   In a one-shot session, `calls` also never carries more tasks than the remaining one-shot budget;
   nodes past it are listed in `held_for_slots`, and `slots.oneshot` shows the limit, the spent count
   and the remaining. When the budget is spent, no call goes out: the held nodes come back as
   `for_parent: [...]` and the say tells you to do each node yourself, write its handoff at the path
   the say gives, and settle it, without `delegate_task` -- those nodes are never offered to a child again.
   `held_for_slots` also lists ready nodes left for the next turn when no free background slot remains.
4. End the turn with one status line. Each completion re-enters as a new turn.
5. On a completion, read the node's handoff file, then `omh_dag action=settle node=<id> outcome=<...>`.
   `accepted` is refused while the handoff file is missing or when Hermes reported the child failed.
   On a Docker or SSH terminal the handoff files live in that terminal, under its user's home, and OMH
   looks there; when it cannot reach it, `accepted` stands with `handoff_checked: false`, and every view
   says `handoff not checked`. With no terminal up yet, `define` hands out nothing: run one terminal
   command there, then `ready`.
   The result carries the next `calls`; dispatch them in the same turn.
6. `omh_dag action=status` at any time; it survives compaction. Every open node carries `open_for_s`, the
   seconds since it first went out. One open past the stuck mark (1 hour) is listed in `stuck`, counted on the
   status line, and named in `say` with what to check: no child took it (dispatch its call again), its child
   still runs (`delegate_task action=list`; settle failed and repair when none is live), or it came back
   unsettled (read the handoff and settle). The profile moves the marks under `plugins.entries.omh.settings`:
   `dag_stuck_after_s` (0 turns the warning off), `dag_stale_after_s` (when `ready` offers again a node no child
   took, default 600) and `dag_max_lost_reoffers` (default 3). OMH still starts no timer: the warning shows on a
   `status`, `ready` or `settle` call, and once at a later turn's start, in an `[OMH dag]` line that also names a
   run with no node running whose next step is yours (a passed `wake_at`, ready nodes, a node out with no child, one
   back and unsettled, or a failure with a repair cycle left), with the one call to make.

A child handing off a still-running background process or CI run is not a failure: settle with
`outcome=parked`, its `handle` (at most 120 characters), and `wake_at` (UTC ISO-8601 or epoch, future,
within 24 hours). The node stays live as `parked`, spends no repair cycle, and cannot be repaired.
At the deadline call `ready`: the same node gets a fresh attempt naming the handle, not replacement
work. OMH starts no timer or poll. After three parks per node, another park is refused with
`park_limit_reached`; settle accepted, failed or blocked instead. Cancel turns parked nodes cancelled.

## When the path is unknown

Define a first run of two or three cheap scout nodes testing different hypotheses: read-only probes,
a spike, or a measurement, each with its own VERIFY and handoff. Once accepted, use `extend` to add
the build layer and its verification node, chosen from those handoffs. This spends one of the run's
two extend rounds; do not commit to the build approach before the scouts report.

## Goal loop

Verify, repair, extend, verify. The verification node runs the real command. When it, or any node, fails:

- read why, then `omh_dag action=repair node=<failed id> nodes=[...]`. Repair nodes may depend only on
  accepted nodes or on each other. Once the latest repair group is all accepted, a failed producer counts
  as done, and a failed verification node is offered again: only its own accepted re-run says the goal
  holds. A node with no role guessed as verify (`role_guess`) is offered again too.
- a node gets at most two repair cycles. The last is a re-plan: the engine briefs those nodes with
  the earlier failure reasons and asks for an approach that differs in kind, not the same retry,
  unless the failures were infrastructure. After that the run state is `stopped`: report what is
  still open, and do not repair again.
- In a one-shot session, repair and extend are refused as `oneshot_budget_exceeded` when they would need
  more children than the remaining one-shot budget; the record is not changed by a refused call.

When every node passed (`state: done`), the result also carries `verdict`, from the record alone:
`verified` only when every producer is under a `verify` node that was accepted with its handoff checked;
otherwise `unverified`, with `verdict_reasons` (`no_verification_node`, `verification_misses:<ids>`,
`handoff_not_checked:<id>`: a checked later verify node clears it). A stopped run whose verify node failed
is `verify_failed`. Report the goal met only on `verified`. An `unverified` done run gets a `role: verify`
node through `extend`, depending on every producer, while rounds are left; after that, report the goal as
unverified. A run of verify nodes alone is judged by those checks. A run where no node wrote files and no
verify node ran is `unverified` with `no_producers`: nothing was built to verify, so report what it
found, not a goal met, and do not extend for it.

Check each node against its SCOPE and the goal criteria too. When work is missing:

- `omh_dag action=extend node=<the node whose check found the gap> nodes=[...]` adds the missing work to
  the same run, with its own verification node. New nodes may depend on the run's accepted nodes and on
  each other; the whole run passes the same refusals as define (cycles, unknown or self edges, a write
  scope shared with any node of the run without an edge, 48 nodes in all).
- a run gets at most two extend rounds (`extend_rounds_left`). After that, report what is still open.

To stop early, `omh_dag action=cancel`; the reply names every child still running (node, subagent id,
how long open) under `still_running`, and they finish on their own unless you stop each with
`delegate_task action=stop`. The cancelled run never settles them.

## Messengers

On Discord, Slack, Telegram, Mattermost and Matrix every completion turn is a bot post.

- Keep `delegation.independent_completions` off (Hermes' default): one completion per call, not per node.
- Dispatch the calls as `ready` groups them (one per category and route), and call `ready` again only on a
  completion, so each turn dispatches what one completion released.
- On an intermediate completion turn, reply with the run's `status_line` only. After a repair or an
  extend it names the added nodes once (`+1 added (repair: Docs body)`); copy it as it is.
- OMH appends the start block, a count line when counts change, and the end block itself; never paste
  the graph into a reply.

In the TUI a completion per node is fine; the panel and `/dag` draw the graph.

## External coding owner

The choice is the router's explicit-choice record (`coding_owner_preference/v1`): the person picked Codex
or Claude Code when asked, or named it in a request, through `omh chat` or `omh coding`. Hermes chat on its
own records no choice, so there every node runs on `delegate_task`. The record is read exactly as the router
reads it, and dag-ulw adds one rule of its own: a choice counts for a day. An external coding CLI spends
the person's money and quota, so a choice older than 24 hours (or dated in the future) starts nothing; the
person names the owner again.

With such a choice:

- `ready`, `settle`, `repair` and `extend` keep the ready coding nodes out of `calls` and list them in
  `export`. A coding node is a `build` node that writes files (`write_scope`): baseline, verify and review
  nodes always run on `delegate_task`, because the builder never approves itself. So does a node sent with
  no role whose label reads like another (`role_guess`); send `role=build` to export it.
- `omh_dag action=export owner=<codex|claude-code>` writes those nodes, and the waiting coding nodes
  whose every open parent goes with them, as a `fanout_contract/v2` units file and a goal file, and
  returns the two `omh coding fanout` commands to run (`prepare`, then `dispatch`). More than four units
  need a `spawn_plan`.
- An exported node is never handed to `delegate_task` again, however long its fanout runs. Settle it from
  the fanout result, writing its handoff file from that result.

Without that choice every node runs on `delegate_task`.
"""
