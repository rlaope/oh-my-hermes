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

People normally talk to Hermes and use only two OMH maintenance commands:
`omh setup` and `omh update`. `omh doctor` is the normal health-check command.
Coding, research, creation, operations, memory, and model-setup requests should
begin as natural-language requests to Hermes.

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
| Use OMH workflows in Claude Code, Codex, Cursor, opencode, OpenClaw, or pi | [Agent Skills projection](AGENT-SKILLS.md) |
| Publish npm/Bun and Homebrew artifacts | [Package-manager distribution](DISTRIBUTION.md) |
| Configure editable Hermes/Maestro model routing | [Installation: Guided Model Setup](INSTALLATION.md#guided-model-setup) |
| Install on native Windows, and know what is POSIX-only there | [Installation: Windows](INSTALLATION.md#windows) |
| Understand what OMH is and is not | [Direction](DIRECTION.md) |
| Understand modules, artifacts, and ownership | [Architecture](ARCHITECTURE.md) |
| Inspect the runtime-readable capability map | [Capabilities](CAPABILITIES.md) |
| Turn a capability family on or off without uninstalling | [Capability Toggles](CAPABILITY-TOGGLES.md) |
| Move a configured profile to another machine or teammate | [Setup Profile Pack](SETUP-PROFILE-PACK.md) |
| Block a Hermes tool call with a rule you wrote | [Toolcall Rules](TOOLCALL-RULES.md) |
| See which of an unattended batch's calls the rules refuse, before it starts | [Toolcall Rules: Rehearsing a planned batch](TOOLCALL-RULES.md#rehearsing-a-planned-batch) |
| See which coding work is running, in which session | [Coding Observability](CODING-OBSERVABILITY.md) |
| Understand measured and unproven impact claims | [Capability Impact](CAPABILITY_IMPACT.md) |
| Browse all generated skills and harness metadata | [Workflow Reference](WORKFLOWS.md) |
| Apply Apple UI design/review/improvement guidance | [Apple Design Guidance](APPLE-DESIGN.md) |
| Track the external skill sources our skills reconstruct | [Skill Upstream Sources](SKILL-SOURCES.md) |
| Prepare coding work for a selected executor | [Delegation-First Completeness](DELEGATION_FIRST_COMPLETENESS.md) |
| Inspect an unattended handoff's advisory risk signals (agents/operators) | [Handoff Risk Scan](HANDOFF-RISK-SCAN.md) |
| Integrate OMH into a Hermes wrapper | [Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md) |
| Capture and recall reviewed project context | [Project Memory](MEMORY.md) |
| Find out which stage failed when a saved memory was not used | [Memory Recall Incident](MEMORY-RECALL-INCIDENT.md) |
| Answer what a web page said as of a date, or compare then versus now | [Temporal Source Receipts](TEMPORAL-SOURCE-RECEIPTS.md) |
| Read a very large PDF, contract, or manual through Hermes in page ranges | [Long Document Reading](LONG-DOCUMENT-READING.md) |
| Judge whether a realtime voice connector keeps whole spoken turns | [Realtime Voice Trial Receipts](REALTIME-VOICE-TRIAL-RECEIPTS.md) |
| See which OMH workflow owns each plugin in the active host catalog | [Plugin Catalog Coverage](PLUGIN-CATALOG-COVERAGE.md) |
| Tell whether a local plugin's declared hooks can block an action or only watch one | [Declared Plugin Hook Contract](PLUGIN-HOOK-CONTRACT.md) |
| Choose a situation-level workflow | [Playbooks](PLAYBOOKS.md) |
| Prepare or verify a release | [Release](RELEASE.md) |

For a pasteable AI-agent install flow, use the
[Agent Install Protocol](../INSTALL_FOR_AGENTS.md). For a visual explanation of
Hermes memory, skills, tools, gateway surfaces, and OMH's role, see the
[Hermes Agent Architecture Guide](../site/docs/hermes-agent-architecture/index.html).

## Six Capability Families

The public front door groups **124 installable skills** by user intent. Exact
skill names remain available for deterministic routing, wrapper rendering, and
operator control.

| Family | Typical work |
| --- | --- |
| **Plan and decide** | Ambiguous goals, `deep-interview`, `ralplan`, `loop`, and reviewed decision paths. |
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
  `omh setup` and `omh update`; broader CLI examples require an
  explicit agent, wrapper, operator, or maintainer label.
- Coding-heavy requests stay executor-neutral until a coding owner is selected.
- Hermes-native aliases/provider bindings stay outside Maestro; Maestro only
  coordinates prepared external handoffs and never executes work.
- Model recommendations and X/Grok affinity are editable editorial order, not
  benchmark or availability claims. Missing heads can use a confirmed compatible
  Qwen, Gemini, Grok, or other alternative; explicit unavailable choices pause.
- `pi` and `senpi` are OMO runtime-family hosts. CCAPI and Apitopia are
  user-declared editorial provider preferences, never probed integrations.
- Wrapper sessions own chat continuity and plan decisions. Linked runtime runs
  own dispatch, execution, verification, review, CI, and merge evidence.
- GitHub issue intake keeps raw content transient: only checked-in issue forms
  can authorize a connector request, each dispatch consumes one stable
  idempotency key, and connector read-back is the sole creation evidence.
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
| Import, inspect, and compare host-collected web QA runs, including the native agent-browser collector boundary | [Web QA Observations](WEB-QA-OBSERVATIONS.md) |
| Record, approve, and replay offline browser workflow traces | [Browser Workflow Traces](BROWSER-WORKFLOW-TRACES.md) |
| Promote an approved browser trace into a project-local skill with exact-diff approval | [Browser Skill Promotion](BROWSER-SKILL-PROMOTION.md) |
| Host-supplied session activity receipts for cross-workflow learning | [Session Activity Receipts](SESSION-ACTIVITY-RECEIPTS.md) |
| Separate what an operator reported from what one run was observed to complete | [Runtime Learning Recap](RUNTIME-LEARNING-RECAP.md) |
| Bind an image result to the route a producer attested, apart from the route requested | [Visual Generation Receipts](VISUAL-GENERATION-RECEIPTS.md) |
| Common oh-my capability axes and gaps | [Parity Matrix](PARITY.md) |
| Implemented application surfaces | [Application Cases](APPLICATION_CASES.md) |
| Public roadmap | [Roadmap](ROADMAP.md) |
| GitHub Pages source | [Website](../site/index.html) |

## Agent And Operator Contracts

These are control-plane contracts for wrappers, host integrators, connector
adapters, and operators. Normal chat users never need them; they are listed here
so that every published contract has a path from this map instead of being
findable only by knowing its filename.

| Contract | Read |
| --- | --- |
| Metadata-only workflow artifact CLI, and the four workflows it dispatches | [Workflow Artifacts](WORKFLOW-ARTIFACTS.md) |
| Host-supplied browser adapter and bounded browser leases | [Browser Adapter](BROWSER-ADAPTER.md) |
| Connector ingress for decision-gate answers | [Decision-Gate Connectors](DECISION-GATE-CONNECTORS.md) |
| Closed ingress for untrusted GitHub tracker evidence | [Tracker Content](TRACKER-CONTENT.md) |
| Write-ahead records for attempted external tool effects | [Egress Attempts](EGRESS-ATTEMPTS.md) |
| Opt-in multi-unit work campaigns for the `ulw-work` engine | [Work Campaigns](WORK-CAMPAIGN.md) |
| Bounded feedback rounds over a closed design-direction set | [Design Direction Iterations](DESIGN-DIRECTION-ITERATIONS.md) |
| Deterministic comparison of submitted cross-harness machine facts | [Cross-Harness Benchmark](CROSS_HARNESS_BENCHMARK.md) |
| Freshness identity behind `omh goal checkpoint` and quality-evidence assessment | [Working-Tree Fingerprint](WORKING-TREE-FINGERPRINT.md) |
| Provider-neutral input fidelity and per-attempt sync receipts for an optional memory provider | [Memory Sync Fidelity](MEMORY-SYNC-FIDELITY.md) |
| Bounded retry/replan/stop/escalate decisions for an observed error | [Failure Mender](failure-mender.md) |

## Documentation Checks

When a public claim changes, check the README, site, capabilities, direction,
architecture, generated workflow reference, and agent contract together.

```sh
PYTHONPATH=tests uv run python -m unittest tests/test_router_content.py -v
uv run python -m omh.cli harness validate
uv run python -m omh.cli docs workflows --check
uv run python -m omh.cli docs navigation --check
git diff --check
```

Three separate evidence classes answer three different questions, and a failure
in one is repaired differently from a failure in another:

| Question | Command | Repair |
| --- | --- | --- |
| Does a generated page still equal its producer? | `docs workflows`/`roles`/`capability-families`/`ulw-*` `--check` | Regenerate from the catalog |
| Does a reviewed sentence still match implementation? | [`docs claims --check`](DOCUMENTATION-CLAIMS.md) | Fix the prose or the code the claim names |
| Can a reader still reach every public page, and does every local link resolve? | `docs navigation --check` | Add the missing link, fix the target, or classify the page |

`docs navigation` starts from the roots declared in
`src/catalogs/documentation_navigation.py` and requires every top-level `docs/`
page to be either reachable from one of them or classified there with a reason
and an owner. A page that is neither fails the check, so an accidental orphan
cannot pass as an intentional one. It reads local files only: no network, no
subprocess, and no automatic edit to any documentation file. Reachability is
discoverability through declared links; it is not evidence that a page's content
is correct, current, or usable.
