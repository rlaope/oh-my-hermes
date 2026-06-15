# OMH Capability Manifests

OMH capability manifests are runtime-readable maps for Hermes, plugin tools, and
wrapper backends. They answer one bounded question:

What can this installed OMH surface prepare, explain, or observe, and what is
still not evidence?

The manifests are not a new source of truth. They are deterministic projections
over existing OMH catalogs and contracts:

- skill metadata from `src/skills/catalog.py`
- role descriptors from `src/catalogs/roles.py`
- routing and locale policy from `src/routing/*`
- wrapper action ids from `src/wrapper/contract.py`
- runtime observation events from `src/runtime/records.py`
- plugin hook/tool metadata from `src/plugin_bundle/omh/*`

Use:

```sh
omh capabilities export --json
omh capabilities export --section keywords --json
omh capabilities list
omh capabilities inspect ultragoal --json
```

The Hermes plugin exposes the same contract through the metadata-only
`omh_capabilities` tool.

## Sections

| Section | Purpose |
| --- | --- |
| `agent_roles` | Responsibility roles such as research, planning, review, and coding handoff. They are descriptors, not runtime agents. |
| `skills` | Skill capabilities, triggers, harnesses, quality bars, handoff policy, and orchestration eligibility derived from the generated skill catalog. |
| `hooks` | Plugin tools/hooks plus wrapper event contracts and whether each surface is only supported or actually observed. |
| `keywords` | Explicit invocation prefixes, natural-language routing rules, locale aliases, conflict policy, and guard rules. |
| `orchestration_patterns` | Safe workflow patterns such as clarify-then-plan, plan-execute-verify, team pipeline, worktree isolation, loop tick, and executor session handoff. |
| `tool_requirements` | Tool/MCP requirements when derivable. PR1 marks this as partial rather than inventing host requirements. |
| `evidence_boundaries` | The shared prepared-vs-observed claim rule. |

## Claim Boundary

Capability presence means OMH can prepare guidance, status, or a handoff. It
does not mean Hermes loaded a plugin, a worker ran, a worktree was created, code
changed, review passed, CI passed, or a PR was merged.

Those claims require matching local wrapper or runtime artifacts such as
`runtime_observation/v1`.

## Why This Exists

Hermes and wrapper surfaces should not need to scrape README prose to know which
skills exist, which actions are safe, or why a route was selected. The capability
manifest gives them a compact local contract while preserving OMH's direction:
Hermes remains the chat surface, selected executors own implementation, and OMH
keeps the evidence boundary visible.
