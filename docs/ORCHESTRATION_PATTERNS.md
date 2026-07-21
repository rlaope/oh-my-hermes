# OMH Orchestration Patterns

OMH orchestration patterns describe how Hermes should shape work before any
executor or runtime claims are made. They are metadata contracts, not hidden
automation.

This is a wrapper and maintainer reference. A normal user describes the work to
Hermes; Hermes or its wrapper selects and inspects the orchestration pattern.

Each pattern names:

- when to use it
- when not to use it
- owner role
- compatible skills
- required decisions
- prepared artifacts
- observed evidence required before status can advance
- wrapper actions that can render the UX

Agents and maintainers can inspect them locally:

```sh
omh capabilities export --section orchestration_patterns --json
omh capabilities inspect executor_session_handoff --json
```

## Included Patterns

| Pattern | Use |
| --- | --- |
| `single_lane` | Direct Hermes-retained work with one owner and one status lane. |
| `clarify_then_plan` | Fuzzy intent that needs a blocking question, plan, and accept/revise gate. |
| `plan_execute_verify` | Work that needs a plan, owner, execution evidence, and verification gate. |
| `fanout_synthesize` | Independent research or option gathering followed by synthesis. |
| `adversarial_review` | A verifier or reviewer challenges a plan, output, or release claim. |
| `team_staged_pipeline` | Multi-lane work where lead/member/verifier ownership is explicit. |
| `swarm_batch` | Independent high-throughput batches with clear ownership. |
| `worktree_isolated_workers` | Parallel implementation that should use isolated workspaces. |
| `loop_run_once` | A bounded loop tick without a daemon or hidden execution. |
| `executor_session_handoff` | Prepared handoff for Codex, Claude Code, Hermes coding skills, or oh-my runtimes. |
| `hermes_coding_team_path` | Optional Hermes-owned coding path with solo, durable-goal, team, and swarm start choices plus an observed runtime ladder. |
| `materials_generation_handoff` | Documents, decks, spreadsheets, PDFs, or other material packages needing generation/QA. |

## Evidence Rule

Prepared pattern metadata is not runtime evidence. For example,
`worktree_isolated_workers` can recommend a worktree policy, but OMH cannot say a
worktree exists until a wrapper or operator records a matching runtime
observation.

This keeps Hermes helpful in chat without pretending to be a hidden executor.

## Multiple Agents, One Home

The patterns above describe a single OMH home coordinating one lane of
work at a time. When more than one agent, wrapper process, or coding
executor is actually running concurrently against the same `~/.omh` and
`~/.hermes` directories, read
[Multi-Agent Operations](MULTI_AGENT_OPERATIONS.md) for the shared-state
ownership model, the Hermes `config.yaml` capability boundary, why
`multi_agent_targets` topology is advisory narration rather than
enforcement, and which upstream-native primitives (Kanban, `delegate_task`,
profiles) OMH prefers to hand work off to instead of reimplementing.
