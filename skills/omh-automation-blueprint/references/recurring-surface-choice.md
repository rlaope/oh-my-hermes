# Choosing Among Heartbeat, Loop, Goal, and Cron

"Keep doing this for me" has four answers in OMH, and they differ in exactly
one thing: what ends them. Decide that first; the stop condition, retry policy,
and delivery target all follow from it.

## The four

| Surface | Ends when | Runs between occurrences | Recommend when |
| --- | --- | --- | --- |
| Cron (`scheduled_ops_blueprint`) | the operator removes the schedule | nothing | the request names a cadence - "every morning", "nightly", "each Monday" |
| Heartbeat (`heartbeat_watch`) | never; the user withdraws it | a liveness check only | the request watches a condition with no cadence and no end state |
| Loop (`loop_start`) | a named verification signal passes | work driven by the last iteration | the request improves something inside a bounded arena |
| Goal (`native_goal`) | a stated stop criterion is met | work driven toward that criterion | the request already states the condition that finishes it |

Two distinctions carry most of the decisions. A cadence answers *when*, so a
request that names one is never a loop, even when the work inside each
occurrence is iterative. And a heartbeat reports without changing anything: the
moment the request asks for something to be fixed between observations, it is a
loop or a goal.

## Each recommendation names the three it beat

A recommendation that does not say why the other three lost is a default, not a
choice, and a user cannot correct a default they cannot see. State each
rejection in the request's own terms - "not a schedule, because no cadence was
named" is checkable, "a heartbeat fits better" is not.

`assess_loopability` emits this as `recurring_surface_comparison`, one reason
per pair, and refuses a recurring recommendation that carries no stop
condition.

## Stop condition

Every recommendation carries one, and it is a condition, never a duration.
"Until the tests pass" is a stop condition; "for two weeks" is an end date,
which belongs in the schedule rather than in the stop rule. A heartbeat's stop
condition is the delivery of a change, not a completion - say that rather than
leaving the field blank, because a blank field reads as "runs forever by
design" when it usually means nobody decided.

## Retry policy

Retry belongs to the surface, not to the task. Name four things before
activation, because the runtime cannot decide any of them:

- **Overlap** - a prior occurrence is still running when the next is due: skip,
  queue, or run concurrently.
- **Missed run** - the host was down through a window: backfill it, or drop it
  and continue at the next occurrence.
- **Repeat failure** - how many consecutive failures pause the surface, and
  whether resuming needs a human.
- **Backoff** - whether a retry waits, and whether that wait is bounded.

A loop and a goal answer these differently from a cron: an iteration that fails
its verification is information the next iteration uses, so a loop's "failure"
is usually not a retry at all. Say which reading applies.

## Delivery target

Name the destination, the silence rule, and what a no-change occurrence does.
The silence rule is the one people skip: a daily digest that sends when nothing
changed trains its reader to ignore it, and one that never sends is
indistinguishable from a broken schedule. Choose one and write it down - report
only on change, or report every occurrence with an explicit no-change line.

## Boundary

A recommended surface, its stop condition, its retry policy, and its delivery
target are a prepared blueprint. OMH starts, skips, queues, retries, and
backfills nothing; a policy decision is not proof the runtime honoured it, and
a saved recurring intent stays paused until an approved runtime surface records
an occurrence against that exact intent revision.
