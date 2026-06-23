# oh-my-hermes

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>Install once. Keep your Hermes workflow. Let OMH make the next step safe.</strong>
  <br>
  <em>Chat-first skills, workflow contracts, status cards, and handoffs that fit existing Hermes setups without breaking them.</em>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-1.0.1%20stable-blue">
</p>

Most people skip the docs. **oh-my-hermes** is built for that reality: install
it, keep working in [Hermes](https://github.com/NousResearch/hermes-agent), and
let the added skills, contracts, and status cards make the next action obvious
without replacing your existing setup.

The product is not "more CLI commands." The `omh` command is setup, repair,
doctor, verifier, and wrapper/backend infrastructure. For
[Hermes](https://github.com/NousResearch/hermes-agent) wrappers and routers,
that CLI contract is a first-class backend surface; for normal users, the main
experience is still chat:

```text
user says a plain request in Hermes
  -> OMH routes it to the right skill/playbook/profile
  -> Hermes explains the next action and evidence boundary
  -> coding is handed off to the selected runtime only when the user or wrapper accepts that path
```

OMH exists for the gap between installation and real use: config checks,
workflow choice, evidence boundaries, and the first useful task. It adds a thin
practical layer of ready-to-use workflows such as `web-research`, `doctor`,
`idea-to-deploy`, `ultragoal`, `loop`, and `ultraprocess` so Hermes can feel
easier to start, easier to trust, and more natural to apply in real work.

> [!NOTE]
> **Friren Agent is hard at work improving OMH inside Art&Engine.**
>
> Improve OMH System !!
>
> <p align="center">
>   <a href="https://rlaope.github.io/artengine-lab/">
>     <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="920">
>   </a>
> </p>
>
> <p align="center">
>   <a href="https://rlaope.github.io/artengine-lab/">
>     <img src="assets/artengine-friren-profile-card.png" alt="Art&Engine profile card for Hope Kim and Friren" width="920">
>   </a>
> </p>

<br>

## Quick Start

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
omh doctor
```

Hermes skill tap path:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

[Website](https://rlaope.github.io/oh-my-hermes/) -
[Documentation](docs/README.md) -
[Installation](docs/INSTALLATION.md) -
[Capabilities](docs/CAPABILITIES.md) -
[Agent Install](INSTALL_FOR_AGENTS.md) -
[Roles](docs/ROLES.md) -
[Application Cases](docs/APPLICATION_CASES.md) -
[GitHub Pages site](site/index.html)

> [!NOTE]
> **GitHub Follow**
> Follow [@rlaope](https://github.com/rlaope) on GitHub for OMH updates and
> related Hermes-native workflow projects.
> Explore [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)
> for the studio behind OMH.

<br>

## Why OMH

- **Hermes stays the surface** - users ask in plain language, and Hermes can
  answer with the right workflow, role, next action, or handoff.
- **Skills install into the workflow you already use** - OMH adds
  Hermes-visible skills and setup repair without asking teams to adopt another
  dashboard.
- **Research and planning feel first-class** - source finding, paper learning,
  web research, briefs, interviews, plans, and strategy work have dedicated
  Hermes-facing paths.
- **Coding is delegated deliberately** - Codex, Claude Code, Hermes, or another
  selected executor can receive a scoped handoff with non-goals, acceptance
  criteria, and verification expectations.
- **Prepared is not observed** - OMH keeps planned handoffs, generated prompts,
  status cards, execution, review, CI, and merge evidence separate.
- **Local and inspectable** - skills, manifests, plans, sessions, and status
  records stay in user-owned local directories.

<br>

## Core Workflows

<p align="center">
  <img src="assets/omh-core-workflows.png" alt="OMH Core Workflows illustration" width="920">
</p>

| Need | OMH helps Hermes do this | Example |
| --- | --- | --- |
| `deep-interview` / `ralplan` / `ultragoal` / `loop` / `ultraprocess` | Shape fuzzy intent into an interview, plan, goal loop, or one PR-ready delivery cycle. | "Make onboarding feel smoother." |
| `feedback-triage` / `research-brief` / `strategy-brief` | Keep product signals, source-backed research, and decisions in non-coding workflows. | "Payment failures keep coming up." |
| `source-finder` / `research-department` / `web-research` / `research-brief` / `report-package` | Prepare typed source candidates, Scout -> Analyst -> Briefer research operations, source-backed evidence, and briefing status boundaries. | "Find papers, datasets, and repos for this topic." |
| `paper-learning` | Explain a supplied paper or paper PDF at very easy, moderate, or expert level while preserving a coverage ledger. | "Explain this arXiv paper without dropping details." |
| `operating-rhythm` / `report-package` / `reliability-review` | Record cadence, reports, and reliability reviews as local artifacts with evidence boundaries. | "Turn the sprint retro and incident review into durable records." |
| `automation-blueprint` / `web-research` / `report-package` | Prepare recurring research or ops blueprints with schedule, delivery, and silence policy. | "Every morning, check competitor news and send a digest only if something changed." |
| `materials-package` / `report-package` | Shape decks, PDFs, spreadsheets, documents, HWP, Markdown, and upload-ready packages. | "Turn the revenue spreadsheet into an Excel and PDF package." |
| `img-summary` | Turn notes, PRs, issues, research, or reports into image-card prompts for a connected image tool. | "Make a PR summary card for reviewers." |
| `idea-to-deploy` / coding runtime handoff / executor selection | Prepare work for Codex, Claude Code, Hermes, or another runtime without hiding execution. | "Turn this issue into a PR-ready plan and hand it to implementation." |
| `agent-ops-review` | Show a manager view of AI-agent research, coding, review, blockers, next actions, and throughput levers. | "As a manager, show the quality and progress of agent work." |

### Img Summary Skill

`img-summary` helps Hermes turn source material into a shareable image-card
prompt. It adapts the card to the source and topic instead of forcing every
summary into one fixed template.

OMH prepares the prompt and handoff. Image generation, visual QA, attachment,
and delivery remain separate until a connected tool or user records them as
observed.

<p align="center">
  <img src="assets/omh-img-summary-card.png" alt="OMH img-summary workflow card showing prompt preparation and observed image evidence boundaries" width="680">
</p>

<br>

## What You Get

| Surface | What it means in practice |
| --- | --- |
| Skill pack | Hermes gets workflows like `loop`, `ralplan`, `source-finder`, `web-research`, `paper-learning`, `materials-package`, `img-summary`, and `ultraprocess`. |
| Setup and repair | `omh setup`, `omh doctor`, `omh update`, and `omh uninstall` keep the local install understandable. |
| Chat workflow picker | Hermes can answer "what can OMH do?" without making the user approve shell commands. |
| OMH context brief | Hermes or a wrapper can fetch a compact OMH mental model, generic-tool checkpoint, and route hint before falling back to ordinary chat/tools. |
| Catalog-aware list | `omh list` groups installed workflows by lane, and `omh list --json` includes descriptions, routing hints, examples, and evidence boundaries for wrappers or operators. |
| Route hint cards | Wrappers can preview the nearest OMH workflow with `chat_route_hint/v1`, even before plugin load is observed. |
| Plugin runtime evidence | Hosts or wrappers can record plugin load/use with `omh plugin observe-host`, and plugin tools/hooks can self-record the same metadata when the host passes observation context; active-ready and historical events stay separate from install smoke. |
| Coding agent paths | Hermes can prepare work for Codex, Claude Code, Hermes itself, or another runtime without pretending the work already ran. |
| Workspace isolation | Hermes can show whether the current workspace is ok, recommend or require a worktree, use `omh worktree prepare` to create one, and use `omh worktree bind` to render open/attach/record actions for the selected coding agent. |
| Agent ops review | Hermes can explain quality gates, blockers, next actions, and throughput levers for AI-agent work without turning a prepared handoff into evidence. |
| Evidence-aware status | Plans, handoffs, dispatch, results, verification, review, CI, and merge readiness stay visibly separate. |
| Workflow learning | Hermes can show learning-readiness and improvement-review cards for workflow attempts, including missed OMH routes: metadata-only trace, deterministic eval, human review queue, non-applying patch proposal, regression case, audit, and export bundle. |
| Organization patterns | Solo, research, product ops, coding runtime, and CTO-style patterns stay available so Hermes can choose the right role flow per request. |

<br>

## Organization Patterns

Profiles describe how Hermes should organize work around a request. They are
role-interaction patterns, not hidden workers. Setup does not need to lock one
organization model; Hermes can choose the pattern per request, and visible role
files remain an explicit advanced option.

<p align="center">
  <img src="assets/omh-profile-interaction-map.svg" alt="OMH request-to-handoff interaction map" width="920">
</p>

<br>

## How It Feels In Hermes

| Plain user message | OMH-shaped Hermes behavior |
| --- | --- |
| "Payment failures keep coming up." | Route to feedback triage or investigation first; prepare reproduction and evidence needs before coding. |
| "Can this issue become a PR?" | Convert the issue into a plan, acceptance criteria, verification commands, and an executor/runtime-neutral handoff. |
| "Prepare next week's strategy meeting." | Use research, meeting, and strategy skills without defaulting to implementation. |
| "Explain this paper at expert level without dropping details." | Use `paper-learning` to choose the explanation level, mark source/PDF extraction evidence, preserve section coverage, and keep figure OCR, citation checking, math validation, reproduction, and peer review unobserved until recorded. |
| "Turn the revenue spreadsheet into an Excel and PDF package with render QA." | Use `materials-package` to scope audience, source inputs, target formats, missing data, QA ladder, and generation handoff without claiming files, screenshots, formulas, approval, or delivery were observed. |
| "Make this repo feel 10k-star quality." | Treat it as a north star, choose a smaller loopable goal, and keep the next verification visible. |
| "Are we ready to release?" | Separate prepared claims from observed test, review, CI, and merge-readiness evidence. |

Advanced team presets, team/swarm readiness, plugin status helpers, the
optional MCP bridge with host-specific config recipes, host-session evidence
records, runtime observation, and release smoke commands are covered in the
documentation below.

<br>

## Documentation

| Need | Read |
| --- | --- |
| Full docs map | [Documentation](docs/README.md) |
| Install, update, reapply, uninstall, and installer flags | [Installation](docs/INSTALLATION.md) |
| AI-agent pasteable install protocol | [Agent Install](INSTALL_FOR_AGENTS.md) |
| Product direction and boundaries | [Direction](docs/DIRECTION.md) |
| Architecture and module ownership | [Architecture](docs/ARCHITECTURE.md) |
| Capability manifests for Hermes/plugin/wrapper use | [Capabilities](docs/CAPABILITIES.md) |
| Orchestration pattern contracts | [Orchestration Patterns](docs/ORCHESTRATION_PATTERNS.md) |
| Common oh-my runtime parity and gaps | [Parity Matrix](docs/PARITY.md) |
| Situation playbooks | [Playbooks](docs/PLAYBOOKS.md) |
| Role surfaces and profile packs | [Roles](docs/ROLES.md) |
| Memory/context review and handoff packs | [Memory Context Review](docs/MEMORY_CONTEXT.md) |
| Discord-style and plugin-native wrapper examples | [Chat Wrapper Examples](docs/CHAT_WRAPPER_EXAMPLES.md) |
| Harness quality contracts | [Harness Quality Contract](docs/HARNESS_QUALITY.md) |
| Representative workflows | [Application Cases](docs/APPLICATION_CASES.md) |
| Public website source | [GitHub Pages site](site/index.html) |

<br>

## Development

Development, release smoke, product readiness, and evidence-bundle details live
in [Release](docs/RELEASE.md). For a quick local sanity check from a source
checkout:

```sh
python3 -m unittest discover -s tests
python3 -m compileall src
python3 -m omh.cli docs workflows --check
```

OMH 1.0.1 is a quality-gated stable baseline. Richer profile activation probes
and more artifact-backed wrapper examples are tracked in the roadmap and
release docs.
