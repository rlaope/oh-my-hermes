# OMH Evidence Boundaries

OMH is a Hermes-native wrapper orchestration layer. It keeps Hermes responsible for chat intake, clarification, source-backed research, planning, and status narration while coding-heavy work is prepared as explicit handoff and tracked only when observed.

## Prepared Versus Observed

Prepared routing, plans, task cards, and handoffs are not execution evidence. `prepared_not_observed` is not implementation, review, CI, merge-readiness, merge evidence, plugin runtime use, or proof that another agent acted.

## Runtime Evidence

When local shell access or a bot wrapper is available, record prepared handoffs and observed workflow evidence under `.omh/runtime/`:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record only what is observed. If Hermes or a chosen oh-my runtime does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.

## Multi-Agent Target Awareness

Wrappers may report `omh_target_topology/v1` when a workspace moves between one Hermes agent target and multiple Hermes agent targets. Treat that topology as setup evidence only. If `active_agent_count` is greater than one, bind this workflow to the current target and thread, name the target boundary in status, and do not claim another Hermes agent observed, accepted, or executed the workflow unless target-specific evidence exists.

If a wrapper reports `single_to_multi` or `multi_to_single`, answer with one concise target-change comment. If the wrapper exposes an `apply_target_change` action and the user accepts it, persist the target registry update; otherwise keep the workflow scoped to the current thread target and ask before assuming multi-agent behavior. A skill that does not need multiple agents should continue as a single-target workflow even when multiple targets are known.

## Memory Context

`memory_review_card/v1` is separate from `status_card/v1`; `handoff_context_pack/v1` may be attached to executor handoffs only when unresolved conflicts are absent.

## Goal Status

`goal_status_card/v1` and `goal_continuation/v1` are goal-execution payloads separate from generic `status_card/v1`; they must name the next action instead of merely summarizing work.

## Hermes Compatibility

- Use Hermes tools and subagents when available.
- Replace unavailable goal tools with file-backed checklists or ledgers.
- Replace unavailable question renderers with one direct question through the current Hermes surface.
- Keep shell bridge behavior explicit and opt-in.
