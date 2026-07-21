# Documentation

This directory is the public operating map for oh-my-hermes. Start with the
job you need Hermes to handle, then open the contract that owns it.

OMH is a Hermes-native wrapper orchestration layer. Hermes owns chat intake,
clarification, source-backed research, planning, and status narration. OMH
provides deterministic local routing, generated skill guidance, wrapper
contracts, prepared handoffs, and evidence records. The selected coding
executor owns coding work when it leaves Hermes.

The core claim boundary is simple: `prepared_not_observed` is useful context,
not execution, provider access, artifact generation, review, CI, deployment,
merge readiness, or a merge.

## Who Runs What

People normally talk to Hermes and use only three OMH maintenance commands:
`omh setup`, `omh update`, and `omh doctor`. Coding, research, creation,
operations, and memory requests should begin as natural-language requests to
Hermes.

The rest of the CLI is an agent and operator control plane. `omh coding`, `omh
runtime`, `omh chat`, `omh memory`, `omh loop`, `omh harness`, and related
commands are primarily called by Hermes Agent, wrappers, coding agents,
automations, or maintainers. This documentation keeps those commands available
for precise integration and debugging, but labels them as backend or operator
references rather than normal user steps.

## Start Here

| Goal | Read |
| --- | --- |
| Install, update, repair, or remove OMH | [Installation](INSTALLATION.md) |
| Understand what OMH is and is not | [Direction](DIRECTION.md) |
| Understand modules, artifacts, and ownership | [Architecture](ARCHITECTURE.md) |
| Inspect the runtime-readable capability map | [Capabilities](CAPABILITIES.md) |
| Understand measured and unproven impact claims | [Capability Impact](CAPABILITY_IMPACT.md) |
| Browse all generated skills and harness metadata | [Workflow Reference](WORKFLOWS.md) |
| Prepare coding work for a selected executor | [Delegation-First Completeness](DELEGATION_FIRST_COMPLETENESS.md) |
| Integrate OMH into a Hermes wrapper | [Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md) |
| Capture and recall reviewed project context | [Project Memory](MEMORY.md) |
| Choose a situation-level workflow | [Playbooks](PLAYBOOKS.md) |
| Prepare or verify a release | [Release](RELEASE.md) |

For a pasteable AI-agent install flow, use the
[Agent Install Protocol](../INSTALL_FOR_AGENTS.md). For a visual explanation of
Hermes memory, skills, tools, gateway surfaces, and OMH's role, see the
[Hermes Agent Architecture Guide](../site/docs/hermes-agent-architecture/index.html).

## Six Capability Families

The public front door groups **82 installable skills** by user intent. Exact
skill names remain available for deterministic routing, wrapper rendering, and
operator control.

| Family | Typical work |
| --- | --- |
| **Plan and decide** | Ambiguous goals, `deep-interview`, `ralplan`, `ultragoal`, `loop`, and reviewed decision paths. |
| **Learn and gather** | Web research, source finding, papers, data, customer signals, and source-backed briefs. |
| **Create materials and visuals** | Frontend, accessibility, visual QA, images, decks, reports, documents, PDFs, and deliverable packages. |
| **Delegate coding and ship** | Scoped, skill-aware handoffs to Codex, Claude Code, Hermes runtime, or another selected executor, plus review and verification gates. |
| **Operate and observe** | Setup, service quality, reliability, releases, sessions, automation, tools, connectors, and workflow learning. |
| **Retain knowledge** | Reviewed project memory, wiki workflows, and provider-neutral external knowledge connections. |

Use [Capabilities](CAPABILITIES.md) for the manifest contract and
[Workflow Reference](WORKFLOWS.md) for the generated catalog.

## Operating Contracts

- Public docs describe local deterministic behavior, not hidden runtime magic.
- Wrapper UX should present actions, status, and evidence states without making
  normal chat users run backend commands.
- User quick starts should foreground natural-language Hermes requests plus
  `omh setup`, `omh update`, and `omh doctor`; broader CLI examples require an
  explicit agent, wrapper, operator, or maintainer label.
- Coding-heavy requests stay executor-neutral until a coding owner is selected.
- Wrapper sessions own chat continuity and plan decisions. Linked runtime runs
  own dispatch, execution, verification, review, CI, and merge evidence.
- Generated workflow docs come from `src/skills/catalog.py`; update the catalog
  before refreshing generated references.
- Project memory under `.omh/memory/` is reviewed OMH-local context. Recall packs
  are not opaque Hermes memory or execution evidence.
- External metric, knowledge, browser, image, video, and connector systems use
  explicit provider boundaries. Configuration is not observed provider I/O.
- Capability impact reports route selection, guidance depth, host availability,
  provider availability, artifact verification, and outcome quality separately.

## More References

| Area | Read |
| --- | --- |
| Responsibility roles and profiles | [Roles](ROLES.md) |
| Safe orchestration patterns | [Orchestration Patterns](ORCHESTRATION_PATTERNS.md) |
| Shared state, locking, and upstream-native coordination for concurrent agents | [Multi-Agent Operations](MULTI_AGENT_OPERATIONS.md) |
| Chat cards and grounded wrapper examples | [Chat Wrapper Examples](CHAT_WRAPPER_EXAMPLES.md) |
| Harness and quality-gate contracts | [Harness Quality Contract](HARNESS_QUALITY.md) |
| Memory/context review and handoff packs | [Memory Context Review](MEMORY_CONTEXT.md) |
| Common oh-my capability axes and gaps | [Parity Matrix](PARITY.md) |
| Implemented application surfaces | [Application Cases](APPLICATION_CASES.md) |
| Public roadmap | [Roadmap](ROADMAP.md) |
| GitHub Pages source | [Website](../site/index.html) |

## Documentation Checks

When a public claim changes, check the README, site, capabilities, direction,
architecture, generated workflow reference, and agent contract together.

```sh
PYTHONPATH=tests uv run python -m unittest tests/test_router_content.py -v
uv run python -m omh.cli harness validate
uv run python -m omh.cli docs workflows --check
git diff --check
```
