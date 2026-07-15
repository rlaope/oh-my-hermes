# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-1.0.2%20stable-blue">
</p>

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>Install once. Keep Hermes. Add a stronger operating layer.</strong>
  <br>
  <em>Planning, research, creation, coding handoffs, operations, and project memory with explicit evidence boundaries.</em>
</p>

**oh-my-hermes** (OMH) turns a normal request in
[Hermes Agent](https://github.com/NousResearch/hermes-agent) into a clear
capability, a useful next step, and an honest statement of what has or has not
happened. It strengthens the Hermes workflow you already use instead of
replacing Hermes or hiding a coding executor behind it.

```text
plain request
  -> choose one of six capability families
  -> prepare a plan, source brief, artifact contract, or coding handoff
  -> record runtime, provider, review, CI, and merge evidence only when observed
```

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md) ·
[Agent Install](INSTALL_FOR_AGENTS.md) ·
[GitHub Pages site](site/index.html)

> [!NOTE]
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="720">
> </p>

## Quick Start

Install the local command and managed skills:

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

Most people only need three direct OMH commands:

- `omh setup` to connect or repair OMH.
- `omh update` to refresh OMH and its managed skills.
- `omh doctor` to check health and get the next repair action.

Everything else begins as a natural-language request to Hermes. Commands such
as `omh coding`, `omh runtime`, `omh chat`, and `omh memory` are primarily a
control plane for Hermes Agent, wrappers, coding agents, and maintainers, not a
workflow that normal users need to memorize.

Then ask Hermes normally:

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

## What OMH Adds

OMH packages **82 installable workflow skills** behind six human-readable
capability families. The family is the front door; exact skill names remain
available when a wrapper or operator needs precise control.

| Capability family | What it helps Hermes do |
| --- | --- |
| **Plan and decide** | Clarify ambiguous goals, prepare reviewed plans, and run durable goal loops. |
| **Learn and gather** | Find sources, explain papers, inspect data, and prepare source-backed briefs. |
| **Create materials and visuals** | Prepare websites, visual QA, images, decks, reports, documents, and deliverable packages with format-specific quality gates. |
| **Delegate coding and ship** | Prepare scoped, skill-aware coding handoffs for Codex, Claude Code, Hermes runtime, or another selected executor. |
| **Operate and observe** | Review setup, service quality, releases, incidents, automation, tools, sessions, and workflow learning. |
| **Retain knowledge** | Build reviewed project memory and connect external knowledge systems through provider-neutral boundaries. |

The full generated catalog, triggers, harnesses, and evidence rules live in
[Workflow Reference](docs/WORKFLOWS.md).

## Built For Real Work

**A stronger router, not a command dump.** English, Korean, Japanese, Chinese,
Spanish, French, German, and Hindi operator requests can be classified locally
without a translation API. OMH returns the recommended family, skill, owner,
next action, and what is still not evidence.

**Better coding handoffs.** OMH can include repository constraints, accepted
scope, worktree guidance, locally available skills, acceptance criteria,
review expectations, and verification gates. Codex, Claude Code, Hermes, and
generic executors remain explicit owners rather than hidden defaults.

**Quality-aware creation.** Frontend, accessibility, image, report, slide,
document, spreadsheet, PDF, poster, and shareable-package requests use
specialized production and QA guidance. A prepared brief is never presented as
a generated or visually verified artifact.

**Provider-neutral operations and memory.** Metric, wiki, browser, image,
video, and connector systems sit behind explicit external-provider contracts.
OMH can validate and analyze supplied data without pretending that a provider
was connected or called.

## Evidence Before Claims

OMH separates useful preparation from observed results:

| State | Meaning |
| --- | --- |
| Prepared | A route, plan, prompt, artifact contract, or handoff is ready. |
| Observed | A wrapper or runtime recorded that an action or result occurred. |
| Verified | A matching test, review, served-surface check, or other required gate passed. |

`prepared_not_observed` is not execution, provider access, artifact generation,
review, CI, deployment, merge readiness, or a merge. Capability impact is
reported across separate dimensions rather than collapsed into one marketing
score. See [Capability Impact](docs/CAPABILITY_IMPACT.md).

## Documentation

- [Documentation map](docs/README.md)
- [Installation and updates](docs/INSTALLATION.md)
- [Product direction and boundaries](docs/DIRECTION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Capability manifests](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [Roles](docs/ROLES.md)
- [Application cases](docs/APPLICATION_CASES.md)
- [Release and development](docs/RELEASE.md)

## Development

For a source checkout:

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH is developed in the open as part of
[Team Art & Engineering](https://rlaope.github.io/artengine-lab/). Follow
[@rlaope](https://github.com/rlaope) for project updates.
