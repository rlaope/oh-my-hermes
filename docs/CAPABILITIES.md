# OMH Capability Manifests

OMH capability manifests are runtime-readable maps for Hermes, plugin tools, and
wrapper backends. They answer one bounded question:

What can this installed OMH surface prepare, explain, or observe, and what is
still not evidence?

The manifests are not a new source of truth. They are deterministic projections
over existing OMH catalogs and contracts:

- skill metadata from `src/skills/catalog.py`
- situation playbooks from `src/catalogs/playbooks.py`
- role descriptors from `src/catalogs/roles.py`
- routing and locale policy from `src/routing/*`
- wrapper action ids from `src/wrapper/contract.py`
- runtime observation events from `src/runtime/records.py`
- plugin hook/tool metadata from `src/plugin_bundle/omh/*`
- optional MCP bridge metadata from `omh mcp manifest`

Use:

```sh
omh capabilities export --json
omh capabilities export --section keywords --json
omh capabilities summary --json
omh capabilities list
omh capabilities inspect ultragoal --json
omh capabilities inspect handoff-guide --section roles --json
omh capabilities inspect request-to-handoff --section playbooks --json
```

The Hermes plugin exposes the same contract through the metadata-only
`omh_capabilities` tool.
Use `action=summary` when Hermes needs to answer "what can OMH do?" or render a
small workflow picker/card without asking the user to approve a shell catalog
command.
Friendly section aliases such as `roles`, `agents`, `patterns`, `tools`, and
`evidence` are accepted as input; JSON responses keep the canonical section
names shown below.

## Sections

| Section | Purpose |
| --- | --- |
| `agent_roles` | Responsibility roles such as research, planning, review, and coding handoff. They are descriptors, not runtime agents. |
| `skills` | Skill capabilities, triggers, harnesses, quality bars, handoff policy, and orchestration eligibility derived from the generated skill catalog. |
| `hooks` | Plugin tools/hooks plus wrapper event contracts and whether each surface is only supported or actually observed. |
| `keywords` | Explicit invocation prefixes, natural-language routing rules, locale aliases, conflict policy, and guard rules. |
| `orchestration_patterns` | Safe workflow patterns such as clarify-then-plan, plan-execute-verify, team pipeline, worktree isolation, loop tick, and executor session handoff. |
| `playbooks` | Situation-level workflow maps such as request-to-handoff, feedback triage, research department, materials processing, and idea-to-deploy, including owner/action hints for the first wrapper card. |
| `tool_requirements` | Tool/MCP requirements when derivable, plus setup guidance for the optional allowlisted OMH MCP bridge. |
| `evidence_boundaries` | The shared prepared-vs-observed claim rule. |

## Claim Boundary

Capability presence means OMH can prepare guidance, status, or a handoff. It
does not mean Hermes loaded a plugin, a worker ran, code changed, review passed,
CI passed, or a PR was merged.

Those claims require matching local wrapper or runtime artifacts such as
`runtime_observation/v1`.

Workspace-isolation guidance uses `worktree_session_isolation/v1`. It can tell a
wrapper to keep the same workspace, recommend a worktree, or require a worktree
before opening a coding agent. It is still prepared guidance until a wrapper or
operator invokes or observes the workspace action. `omh worktree prepare` is the
explicit opt-in backend that can create a local Git worktree and record
`omh_worktree_observation/v1`; that record proves workspace isolation only, not
executor dispatch, implementation, review, CI, or merge.

The optional MCP bridge uses `omh mcp serve` and exposes only `omh_status`,
`omh_recommend`, and `omh_probe`. Bridge availability is not host-load evidence,
and a host config file is not proof that any MCP tool was called. A host or
wrapper that actually observes bridge load or use can record
`omh_mcp_host_session/v1` with `omh mcp observe-host`; that remains session
evidence only.

## Why This Exists

Hermes and wrapper surfaces should not need to scrape README prose to know which
skills exist, which actions are safe, or why a route was selected. The capability
manifest gives them a compact local contract while preserving OMH's direction:
Hermes remains the chat surface, selected executors own implementation, and OMH
keeps the evidence boundary visible.
