# dag-ulw run loop

## The calls, in order

1. `omh_dag action=define run=<id> name=<short name> goal=<one line> criteria=[...] nodes=[...]` (criteria: see
   Goal criteria below). A refusal names what to fix:
   a cycle, an unknown or self dependency, two nodes writing one path with no edge between them, more than
   48 nodes, an empty graph, a node whose prompt names none of TASK / DELIVERABLE / SCOPE / VERIFY /
   STOP WHEN, and in a finite one-shot session (`hermes chat -q`) more nodes than the budget REMAINING in
   this process: `delegation.oneshot_max_children` (default 2, 0 = unlimited; a value that is not a positive
   integer uses the default; interactive sessions are never capped) minus the children already delegated
   this run, including non-dag `delegate_task` calls. If the host's one-shot detector itself
   cannot be read, define is refused as `oneshot_detection_unavailable` rather than run uncapped;
   `ready`, `settle`, `repair` and `extend` refuse it the same way, and the record is untouched.
   The nodes share one worktree: dependents and the verify node read earlier nodes' edits from it. With
   Hermes' `delegation.worktree_isolation` on and a local terminal, each child would start from the last
   commit without them, so define is refused as `worktree_isolation_on`, and a run defined before it was
   turned on hands out no call while it is on (`status` says why). OMH never writes the setting: relay the
   say, which names `hermes config set delegation.worktree_isolation false` for the person to run.
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
   `ultrabrain`, a graph defined with 4+ nodes and no `ultrabrain`, `architect` or `forensics` node
   (`no_judgement_node`: when one node's judgement decides the run, give it `ultrabrain`; otherwise go
   on), and a graph of 5+ nodes whose critical path is at least 80% of it (`serial_graph`: split it
   into parallel lanes where the work allows).
2. The result carries `calls`. Each call is one category (and route: a node retried after a provider error
   goes in a call of its own): run its `route` with `omh_delegate_route` (`set`, or `fallback`), then one
   `delegate_task` with its `tasks` unchanged. The goal ends with `[dag:<run>/<node>]`; that marker is how
   OMH ties the child to its node. A node after a repaired one is told to read the repair's handoff files.
   When Hermes (0.22.5+) runs a delegation backend other than `default`, the route names that `backend`
   instead and no route tool runs. Under `model_map` each task carries the user's `option` for its category
   (a retry takes the category's next option; a category no option matches carries none and runs on the
   backend's default). Under `profile_routes` OMH picks no profile: the tasks go as they are. Views name the
   option Hermes reports the child ran on, and a lane keeps its category only when that is the option handed out.
   In `swarm`, `quick` and `simple-work` an option with a fast `service_tier` is tried before the same model's
   normal one; elsewhere the normal one leads. Mark a node `local: true` when its material must not leave the
   machine (customer data, keys, private documents): it runs only on a `model_map` option whose `base_url` is
   on this machine or its private network (or provider `lmstudio`/`llamacpp`), a retry takes the next local
   one, and with none left it is listed in `held_for_local_model`, never sent to a cloud model. Tell the
   person; they add a local option or the node is settled blocked.
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

## Goal criteria

Split the goal into the outcomes that can each be checked on their own, from what the request names, and
pass them at define as `criteria=[{id, text}, ...]`: 1 to 12, each a short id and one line. Keep
`goal` to one short line of what the request is for; its conditions go into criteria, not the goal. A
criterion names the state the person asked for, "it works on staging", not that a check was run or its
result reported ("staging check reported", "staging checked"): that state is what the verify node
confirms. Never ask the person to list them. A non-list, more than 12, a duplicate id, or a field other than id and text is
refused as `invalid_criteria`; an empty list is the same as none. Leaving them out is allowed (lint
`no_goal_criteria`), and the run then works as it did before criteria existed. Criteria are part of the run:
the same run id defined with other criteria is refused as `run_exists`. `extend` takes new `criteria` too
(new ids only, 12 in all); nothing rewrites or removes one, and `repair` takes none.

Each verify node's task lists the criteria and asks for one handoff line per criterion, marked with its
attempt's own random token, which the task prints (a re-run, a provider-error retry and a resumed park get a
new one; the same attempt offered again keeps it):

    CRITERION <id> #<token>: met | unmet | unobserved - <the command it ran and what it showed>

OMH reads only those lines, at a line's start (spaces, `-`, `*` or backticks before it are fine), for the
ids the run declares and this attempt's token, so no line written for another attempt ever counts. After the
status comes nothing or a separator (`-`, `:`, a dash) and the evidence; anything else (`?`, `(`, `/`, `|`)
makes it no criterion line. `met` needs evidence with a letter or digit, not the `<...>` placeholder. A read
on a Docker or SSH terminal that timed out, failed or came back without its end mark is unread, like one
OMH cannot reach. The last line per id wins, and a criterion with
no line counts as `unobserved`. Ids read in lower case (`C1` is `c1`). `unmet` means the check ran and the
outcome is not there; `unobserved` means the check could not run here. Read those lines before settling: settle
the verify node accepted only when every one says met, failed when one is unmet, blocked when one could not be
checked here. It keeps the status word only. Settling that verify node:

- `accepted` with a criterion `unmet` is refused as `criteria_unmet`: settle it failed, then repair it with
  nodes that fix the work. The say names what checks again: the node itself, the verify node it repairs, or,
  for a verify node inside another node's repair group (which does not run again), the verify nodes after
  that node, else a role=verify node you add to the new group.
- `accepted` with one `unobserved` is refused as `criteria_unobserved`: settle it failed and repair it so they
  are checked, or settle it blocked when they cannot be checked here.
- A handoff on this host that exists but cannot be opened refuses `accepted` as `handoff_unreadable`.
- `failed` and `blocked` record what the handoff marks; a missing handoff does not refuse them, but an
  interrupted read on a Docker or SSH terminal refuses them as `settle_interrupted` (settle again). A handoff
  OMH could not read records nothing. The result still carries `criteria`, and its `say` counts them, so the
  report says how far the goal got (11 of 12 confirmed, one could not be checked here, and why).

Each verify node counts with its last attempt only. `verified` also needs every criterion `met` by an
accepted verify node whose handoff was read (the newest per criterion); otherwise the run is `unverified` with `criteria_unmet:<ids>` or `criteria_unobserved:<ids>`,
so criteria an extend round added need a verify node that checks them. The result carries `criteria`
(`total`, `met`, the `unmet` and `unobserved` ids, and each item with its status, `unchecked` before any
read), and the status line and the done `say` add `2/3 criteria met`; `status` shows the same after
compaction. In the report, say how many were met and which were not met or could not be checked, in plain
words: the status words are the tool's, not the person's.

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
`verified` only when every producer is under a `verify` node that was accepted with its handoff checked
(and, with criteria, each one met: see Goal criteria); otherwise `unverified`, with `verdict_reasons`
(`no_verification_node`, `verification_misses:<ids>`, `handoff_not_checked:<id>`: a checked later verify
node clears it). A stopped run whose verify node failed
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

A coding-owner choice counts only for the request it was made in, as it does for `ulw-maestro`: an
external coding CLI spends the person's money and quota. The person chooses by naming Codex or Claude Code,
or both, in a request that invokes dag-ulw (`/dag-ulw <goal> with codex`, `dag-ulw로 ... codex로`); a
request that only reads as big work, without invoking dag-ulw, names no owner. `define` keeps the owners
that request named for the whole run, and only for that run. An earlier request's choice, a choice made in
`omh chat` or `omh coding`, and a recorded preference never count. When the person wants an external owner
and this request names none, ask them to name it in a request that invokes dag-ulw; do not reuse an
earlier one. Defining the same run again changes nothing, so a newly named owner needs a new run id (or
cancel this run and define one under a new id; a cancelled run id is not defined again).

With such a choice:

- A coding node may carry `owner: codex` or `owner: claude-code`. Only coding nodes may carry it: a coding
  node is a `build` node that writes files (`write_scope`). Baseline, verify and review nodes always run
  on `delegate_task`, because the builder never approves itself. So does a node sent with no role whose
  label reads like another (`role_guess`); send `role=build` to export it.
- A node that names an owner the request chose goes to that owner; one that names an unchosen owner runs on
  `delegate_task`, not another owner. A node that names no owner runs on `delegate_task`, whatever was chosen.
- `ready`, `settle`, `repair` and `extend` keep chosen-owner coding nodes out of `calls` and list batches
  in `exports`, one entry per owner, sorted by owner (`owner`, `nodes`, `next`). `status` shows the same
  split. The unchanged single-owner `export` object appears only when `exports` has exactly one entry.
- Call `omh_dag action=export owner=<codex|claude-code>` once per listed owner. Each writes that owner's
  ready nodes and waiting coding nodes whose every open parent joins the same batch as a `fanout_contract/v2`
  units file and a goal file, returning the commands to run: `omh coding fanout prepare` then `dispatch`, or one
  `omh coding run` for a single node.
  A node waiting on another owner or a native node waits until that parent settles before export.
  More than four units need a `spawn_plan`.
- An exported node is never handed to `delegate_task` again, however long its fanout runs. Settle it from
  the fanout result, writing its handoff file from that result.

Without that request's choice, a node runs on `delegate_task`.
