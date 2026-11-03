# dag-ulw run loop

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

## Goal loop

Verify, repair, extend, verify. The verification node runs the real command. When it, or any node, fails:

- read why, then `omh_dag action=repair node=<failed id> nodes=[...]`. Repair nodes may depend only on
  accepted nodes or on each other. Once the latest repair group is all accepted, a failed producer counts
  as done, and a failed verification node is offered again: only its own accepted re-run says the goal
  holds. A node with no role guessed as verify (`role_guess`) is offered again too.
- a node gets at most two repair cycles. After that the run state is `stopped`: report what is still
  open, and do not repair again.
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
