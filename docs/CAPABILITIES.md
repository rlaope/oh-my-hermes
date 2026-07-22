# OMH Capability Manifests

OMH capability manifests are runtime-readable maps for Hermes, plugin tools, and
wrapper backends. They answer one bounded question:

This is an agent, wrapper, and maintainer reference. Normal users ask Hermes
what OMH can do; they do not need to run the capability commands below.

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
- optional MCP bridge metadata from `omh mcp manifest` and host recipes from
  `omh mcp config-recipe`

Use:

```sh
omh capabilities export --json
omh capabilities export --section keywords --json
omh capabilities summary --json
omh capabilities impact
omh capabilities impact --json
omh capabilities list
omh capabilities inspect ultragoal --json
omh capabilities inspect handoff-guide --section roles --json
omh capabilities inspect request-to-handoff --section playbooks --json
omh context brief "make an image card for this PR" --json
```

The Hermes plugin exposes the same contract through the metadata-only
`omh_capabilities` tool, exposes `omh_context` when Hermes needs the compact
OMH mental model, generic-tool checkpoint, and optional message route hint in
one payload, exposes `omh_interact` when Hermes needs a renderable
`chat_interaction/v1` plus a metadata-only wrapper session record, exposes
`omh_recommend` when Hermes only needs route hints, and exposes `omh_probe`
when Hermes needs local setup/runtime status or a capability roadmap without
asking the user to approve a shell command.
Use `action=summary` when Hermes needs to answer "what can OMH do?" or render a
small workflow picker/card without asking the user to approve a shell catalog
command.
Use `action=impact` to separate locally proven route selection from guidance,
host load, provider availability, artifact verification, and comparative
outcome claims. The report intentionally has no aggregate capability score.
Friendly section aliases such as `roles`, `agents`, `patterns`, `tools`, and
`evidence` are accepted as input; JSON responses keep the canonical section
names shown below.

The summary also includes `capability_families`, the user-facing front door for
normal chat surfaces:

| Family | What Hermes should show first |
| --- | --- |
| Plan and decide | Clarify goals, prepare plans, and make loop or decision paths explicit. |
| Learn and gather | Find sources, explain papers, triage signals, and prepare source-backed briefs. |
| Retain knowledge | Capture reviewed project knowledge and prepare provider-neutral wiki or external knowledge connections without claiming writes. |
| Create materials and visuals | Shape files, reports, packages, and image-card prompts before generation is claimed. |
| Delegate coding and ship | Prepare scoped handoffs and dynamic typed target workflow charts across model, runtime, wrapper, tool, and agent surfaces after scope is clear. |
| Operate and observe | Show setup health, automation, workflow learning, memory review, status, and repair next steps. |

Capability families are the public, user-facing front door. The older lanes and
groups remain in the manifest as compatibility context for wrappers, tests, and
existing plugin surfaces; they should not be introduced to normal users before
the family layer.

## Sections

| Section | Purpose |
| --- | --- |
| `agent_roles` | Responsibility roles such as research, planning, review, and coding handoff. They are descriptors, not runtime agents. |
| `skills` | Skill capabilities, triggers, harnesses, quality bars, handoff policy, and orchestration eligibility derived from the generated skill catalog. |
| `hooks` | Plugin tools/hooks plus wrapper event contracts and whether each surface is only supported or actually observed. |
| `keywords` | Explicit invocation prefixes, natural-language routing rules, locale aliases, conflict policy, and guard rules. |
| `orchestration_patterns` | Safe workflow patterns such as clarify-then-plan, plan-execute-verify, team pipeline, dynamic typed target workflow, worktree isolation, loop tick, and executor session handoff. |
| `playbooks` | Situation-level workflow maps such as request-to-handoff, feedback triage, research department, materials processing, and idea-to-deploy, including owner/action hints for the first wrapper card. |
| `tool_requirements` | Tool/MCP requirements when derivable, plus setup guidance for the optional allowlisted OMH MCP bridge. |
| `evidence_boundaries` | The shared prepared-vs-observed claim rule. |

## Claim Boundary

Capability presence means OMH can prepare guidance, status, or a handoff. It
does not mean Hermes loaded a plugin, a worker ran, code changed, review passed,
CI passed, or a PR was merged.

`omh coding dynamic-workflow` prepares `dynamic_coding_workflow/v1` and an SVG
`dynamic_coding_workflow_chart/v1` image attachment that names each prepared
stage's role, target, target type, model, cost tier, and gate. The artifact is
a workflow proposal for a wrapper or operator to show in chat; it is not target
selection, runtime dispatch, model invocation, review, verification, CI, or
merge evidence until matching observed records exist.

Model, runtime, wrapper, tool, and agent targets are distinct. A GLM-like entry
is a model target; a Pi-like entry is a runtime or agent surface target.
Defaults describe dynamic planning, implementation, and review target pools
instead of preselecting concrete models, runtime agents, tools, or wrappers.

Those claims require matching local wrapper or runtime artifacts such as
`runtime_observation/v1`.

Workspace-isolation guidance uses `worktree_session_isolation/v1`. It can tell a
wrapper to keep the same workspace, recommend a worktree, or require a worktree
before opening a coding agent. It is still prepared guidance until a wrapper or
operator invokes or observes the workspace action. Worktree creation is deferred
to native tooling — upstream Hermes manages worktrees (Kanban worktree-per-task
since v0.15.0, Desktop Projects since v0.18.0) or you can run `git worktree add`
— and OMH records `omh_worktree_observation/v1` for the resulting worktree.
`omh worktree bind` can then return
`worktree_executor_binding/v1` so a wrapper can show open/attach/record actions
for the selected coding agent. Those records prove workspace isolation and
session-start guidance only, not executor dispatch, implementation, review, CI,
or merge.

The optional MCP bridge uses `omh mcp serve` and exposes only `omh_status`,
`omh_recommend`, and `omh_probe`. `omh_probe` can include the parity matrix and
capability roadmap when the host asks for them. `omh mcp config-recipe --host
claude-code|codex|opencode|cursor|generic` can print copy-paste snippets for
common MCP-capable hosts. `omh setup --with-mcp --mcp-host
codex|claude-code|opencode|cursor` can also write the local host config entry
directly. Bridge availability and host config text are not host-load evidence.
A host or wrapper that actually observes bridge load or use can record
`omh_mcp_host_session/v1` with `omh mcp observe-host`; that remains session
evidence only.

The managed plugin bridge has the same split. Local install/import/register
smoke proves the bundle is present and importable, including tools such as
`omh_interact`, `omh_context`, `omh_recommend`, `omh_capabilities`,
`omh_probe`, `omh_hud`, and `omh_status`.
`omh_probe` can return the same capability roadmap shape as `omh probe
--roadmap`; in standalone plugin-bundle mode it returns a degraded roadmap that
only uses local files and metadata. Host or wrapper evidence that Hermes
actually loaded or used the plugin is recorded separately with
`omh plugin observe-host`, or self-recorded by an invoked plugin tool/hook when
the host passes bounded `observation` metadata, as
`omh_plugin_host_observation/v1`. Active readiness requires the latest observed
event to be `plugin_load`, `tool_call`, `hook_call`, or `status_query`;
`blocked`, `session_end`, and `plugin_unload` do not make the native bridge
active.

## Why This Exists

Hermes and wrapper surfaces should not need to scrape README prose to know which
skills exist, which actions are safe, or why a route was selected. The capability
manifest gives them a compact local contract while preserving OMH's direction:
Hermes remains the chat surface, selected executors own implementation, and OMH
keeps the evidence boundary visible.
