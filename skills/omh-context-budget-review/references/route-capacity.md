# Route-Bound Context Budget

A context plan prepared under one provider/model can look valid after the host
switches routes even though the window, output allowance, compaction reserve, or
retained-history target changed. This reference binds `context_budget_plan/v1`
to the route it was computed for and states what OMH can and cannot observe.

Load it when a long task starts, when the route changes, when the hook prints
`[OMH Context Budget]`, or when someone asks which route the budget rests on.

## Who publishes what

Hermes never learns provider capacity by itself. An agent or operator publishes
it for one host session; the commands below are control-plane references, not
steps a chat user runs.

```sh
omh context budget-plan prepare --session-ref <session> --executor-profile <profile> --provider <provider> --model <wire-model> --capacity capacity.json --must-keep keep.json
omh context budget-plan rebind  --session-ref <session> --executor-profile <profile> --provider <provider> --model <wire-model> --capacity capacity.json
omh context budget-plan status  --session-ref <session> [--json]
```

`capacity.json` is `route_capacity_input/v1`: `context_window_tokens`,
`max_output_tokens`, `compaction_reserve_tokens`, and `retained_history_tokens`,
each `{"value", "class", "source", "observed_at"}`. A field left out stays
`unknown`. `keep.json` is the must-keep pack as `{"digest", "estimated_tokens_total", "item_classes"}`, where `item_classes` maps a class from the closed seven (`prohibitions`, `decisions`, `open_questions`, `requirements`, `paths`, `pr_state`, `verification_gaps`) to `{"count": N, "refs": [...]}` with at most 8 refs; omit `item_classes` only when you did not count, and the later class comparison is then unavailable;
the pack's text never enters the plan file. `--model` is the exact wire spelling
the host will send, not a family alias. `--provider` is declared local metadata;
without it the route stays provider-unknown.

The plan is written under `runtime/context-budget-plans/` keyed by a session
digest, so a plan for one session is invisible to every other session.

## Evidence classes

| Class | Meaning | Effect on the usable budget |
| --- | --- | --- |
| `observed` | A caller-supplied observation with a UTC clock in `observed_at` | Counts toward `usable_budget_tokens` |
| `assumed` | A user or heuristic value | Stays visible as an operand; the usable budget reports `assumed` with no number |
| `unknown` | Not stated | The usable budget is `unknown`; nothing is inherited from the previous route |

The usable budget is `context_window - max_output - compaction_reserve -
retained_history`, and the derivation is recorded next to the result. Clocks in
`observed_at` are the caller's evidence clocks; OMH adds no TTL and consults no
documentation to upgrade them.

## Invalidation

`rebind` compares the new effective capacity digest with the active one.

| Outcome | `invalidation.reason` | `invalidation.action` |
| --- | --- | --- |
| Same effective values, any identity change | previous reason | previous action; `plan_id` and the pack are preserved |
| Any effective value changed | `capacity_changed` | `checkpoint_required` |
| Usable budget shrank | `capacity_shrank` | `checkpoint_required` |
| Must-keep estimate exceeds the usable budget | `capacity_shrank` or `capacity_changed` | `overflow_recovery_required` |
| Usable budget or provider unknown | `capacity_unknown` | `capacity_unknown_hold` |
| Ninth changed rebind | `rebind_limit` | `rebind_loop_hold` |

`stale` is true whenever the action is anything but `continue`. A changed
rebind gets a new `plan_id` and records the old one in `superseded_plan_id`;
the last eight route identity digests stay in `route_history`.

## What the hook sees

On every model call `pre_llm_call` reads the plan for the current session and
adds `omh_context_budget` (`context_budget_continuation/v1`) plus one
`[OMH Context Budget]` line. The host supplies only the wire model. Only an
exact match with the published `wire_model` makes the published capacity
eligible; a mismatch yields `host_route_unbound` and an unreadable file yields
`plan_unreadable`, both as `capacity_unknown_hold`. `host_route.provider` is
always `null` and `provider_observation` is always `unknown`: the host never
tells OMH which provider served the call.

The projection is a prepared obligation. `recovery.max_checkpoint_attempts` is
1 and `recovery.completion` is `not_observed`: resolve the hold with one
checkpoint or capacity review, keep the must-keep pack, then publish the plan
again. The hook does not block the provider call and does not compact anything.

## Status language

`status` prints the route, the usable budget with its class, each capacity field
with its class, source, and clock, and the continuation action. It always ends
with the same boundary: provider usage, compaction, and billing are
`not_observed`. `local_token_estimate` is the pack's estimate and is `assumed`.
Say which route and evidence the budget rests on and whether a replan is owed;
do not say the host compacted, the provider counted, or a bill accrued.

## Boundary

No network lookup, no entitlement check, no billing claim, no hidden compaction.
Digests exclude credentials and prompt text. A published plan is not proof that
any model received the must-keep pack.
