# oh-my-hermes-agent

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes Agent" width="720">
</p>

<p align="center">
  <strong>Install once. Talk to Hermes. Let OMH shape the work.</strong>
  <br>
  <em>Hermes-native skills, workflow contracts, evidence-aware status, and executor-ready handoffs.</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-1.0.0%20stable-blue">
</p>

**oh-my-hermes-agent** makes Hermes Agent feel more capable after install. OMH
adds workflow skills, optional profiles, wrapper-facing contracts, local
evidence records, and coding handoff preparation while keeping normal users in
Hermes chat.

The product is not "more CLI commands." The `omh` command is bootstrap,
doctor, verifier, and wrapper/backend infrastructure. The main experience is:

```text
user says a plain request in Hermes
  -> OMH routes it to the right skill/playbook/profile
  -> Hermes explains the next action and evidence boundary
  -> coding is handed off only when the user or wrapper accepts that path
```

> Have you ever felt that Hermes Agent is powerful, but still has a high
> barrier to entry? OMH exists for that gap between installation and real use:
> setup, config checks, verification, workflow choice, and the first useful
> task. The engine is already strong across Skills, Gateway, Profiles, and
> Cron; OMH adds a thin practical layer of ready-to-use workflows such as
> `web-research`, `doctor`, `idea-to-deploy`, `ultragoal`, and `loop` so Hermes can
> feel easier to start, easier to trust, and more natural to apply in real
> work.

[Website](https://rlaope.github.io/oh-my-hermes-agent/) -
[Documentation](docs/README.md) -
[Installation](docs/INSTALLATION.md) -
[Agent Install](INSTALL_FOR_AGENTS.md) -
[Roles](docs/ROLES.md) -
[Application Cases](docs/APPLICATION_CASES.md) -
[GitHub Pages site](site/index.html)

> [!NOTE]
> **GitHub Follow**
> Follow [@rlaope](https://github.com/rlaope) on GitHub for OMH updates and
> related Hermes-native workflow projects.
> Explore [ArtEngine Lab](https://rlaope.github.io/artengine-lab/) for the
> Art & Engineering studio behind OMH.

---

## Quick Start

Install OMH and apply the Hermes setup:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
```

The installer normally runs setup for you. Keep `omh setup` in the quick start
because it is the repeatable repair step that installs generated skills under
`~/.omh/skills` and registers them with Hermes through `skills.external_dirs`.

Verify the local install:

```sh
omh doctor
```

The installer creates an isolated OMH virtual environment, links the `omh`
command into `~/.local/bin` when possible, and prints the installed command
path. If that directory is not on `PATH`, add the printed directory to `PATH`
or run the printed absolute `omh` path directly.

Then talk to Hermes:

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

Hermes should explain why `request-to-handoff` is the right first workflow,
name the responsible role, show the next action, and say what is not evidence
yet. Users should not need to know `omh recommend`, `omh chat interact`, or
other backend commands for normal use.

If your Hermes environment supports native skill taps, this is the equivalent
Hermes-native front door:

```sh
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes
```

Use the full identifier above for the first install. It avoids short-name
resolver ambiguity in current Hermes CLI releases and still installs the
`oh-my-hermes` skill.

For pinned releases after a matching `v<version>` tag exists:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

## Why OMH

<p align="center">
  <img src="assets/omh-flagship-workflows-poster.png" alt="OMH flagship command sets poster" width="920">
</p>

- **Natural-language first** - users in chat do not need to know `omh` commands.
- **Install-first, not dashboard-first** - get Hermes-visible skills without
  adopting a hosted service, bot SDK, or separate app.
- **Hermes-native boundary** - no Hermes core patching, hidden transport bot, or
  network service inside this package.
- **Delegation-first coding** - coding-heavy requests become prepared handoffs
  for the selected executor: Codex when supported, or prompt-only handoff for
  Claude Code, generic agents, OMH-style runtimes, or Hermes-retained work.
- **Evidence-aware status** - prepared, dispatched, executed, reviewed,
  verified, CI, and merge-ready states stay separate.
- **Durable goal mode contracts** - long work can stay tied to `.omh/goals`
  ledgers, completion gates, and explicit "continue/checkpoint/block/complete"
  next actions instead of ending with a vague summary.
- **Loop runtime ticks** - ambitious `./loop` goals can be advanced by a local
  tick with a deterministic queue shape for worktree, subagent, connector, and
  handoff plans without pretending those steps already ran.
- **Local and inspectable** - skills, manifests, plans, sessions, and runtime
  records live in user-owned local directories.

## Flagship Command Sets

| Representative workflow | Boundary | Plain request |
| --- | --- | --- |
| `deep-interview` / `ralplan` / `ultragoal` / `loop` | Hermes turns ambiguous intent into a concrete goal, plan, execution-ready path, or direct ambitious goal loop. | "Make onboarding feel smoother." |
| `feedback-triage` / `research-brief` / `strategy-brief` | Hermes keeps non-coding company and product operations inside brief, evidence, and decision workflows. | "Payment failures keep coming up." |
| `idea-to-deploy` / coding handoff / executor selection | Hermes prepares work for Codex, Claude Code, or another selected executor instead of hiding coding inside Hermes. | "Turn this issue into a PR-ready plan and hand it to implementation." |

## What You Get

| Surface | What it provides |
| --- | --- |
| Hermes skill tap | Tap-compatible skills under `skills/<name>/SKILL.md`. |
| Bootstrap setup | `omh setup` installs generated skills and registers `skills.external_dirs`. |
| Flagship playbook | `request-to-handoff` turns a plain Hermes message into a role-owned next action with an evidence boundary. |
| App operation loops | `idea-to-deploy`, `cto-loop`, and `deploy-and-monitor` make Hermes feel like an app delivery operator while keeping evidence boundaries strict. |
| Ambitious goal loops | `loop` lets Hermes run a direct high-level goal cycle across interview, research, planning, runtime tick queueing, handoff, feedback, waiting, and resume states inside an explicit permission profile. |
| Business workflows | Research briefs, strategy briefs, meeting briefs, feedback triage, and ops review for non-coding company work. |
| Coding handoffs | Executor-neutral handoff payloads with acceptance, review, and verification expectations. |
| Memory context review | Review OMH-local and wrapper-supplied context, flag stale assumptions, and attach conflict-free summaries to executor handoffs. |
| Strict goal progress | `.omh/goals` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, and `goal_continuation/v1` keep long-running goals from being treated as done before evidence is ready. |
| Wrapper contracts | `chat_interaction/v1`, status cards, action ids, and local runtime artifacts for Discord, Slack, or hosted adapters. |
| Optional plugin bridge | `omh setup --with-plugin` installs `~/.hermes/plugins/omh` with metadata-only `omh_status` support. |
| Optional team profile packs | CTO/PM-style or delivery/research role files can be installed only when selected. |

## How It Feels In Hermes

| Plain user message | OMH-shaped Hermes behavior |
| --- | --- |
| "Payment failures keep coming up." | Route to feedback triage or investigation first; prepare reproduction and evidence needs before coding. |
| "Can this issue become a PR?" | Convert the issue into a plan, acceptance criteria, verification commands, and an executor-neutral handoff. |
| "Prepare next week's strategy meeting." | Use research, meeting, and strategy skills without defaulting to implementation. |
| "Take this idea from plan to deploy and monitor it safely." | Shape the idea, record decision gates, prepare an executor handoff only if code is accepted, then track release/deploy/monitor status separately. |
| "Run a CTO loop for roadmap and release readiness." | Structure PM, architecture, delivery risk, release readiness, and follow-up decisions without forcing hidden role agents. |
| "./loop make this a 10k-star quality OSS." | Start a direct ambitious goal loop, preserve the large goal, queue worktree/subagent/connector plans through runtime ticks with deterministic queue shapes, separate implementable work from external waiting, and keep execution behind the selected permission profile. |
| "Deploy and monitor this release with rollback checks." | Show release scope, go/no-go, health signals, rollback gate, and post-deploy status without claiming infrastructure execution. |
| "This refactor feels risky." | Produce a bounded plan, risk notes, review expectations, and a coding-agent handoff only after acceptance. |
| "Are we ready to release?" | Separate prepared claims from observed test, review, CI, and merge-readiness evidence. |

For company and app operation work, OMH can help Hermes classify, brief, decide,
handoff, and track the next workflow without pretending data was fetched, a
meeting happened, code was implemented, or a deployment was observed.

## Optional Profiles And Plugin

Most installs only need the skill layer. Operators can opt into profiles or the
thin plugin bridge when the target Hermes environment benefits from them.

```sh
omh profile list
omh profile inspect cto-loop
omh setup --profile-pack cto-loop
```

Profile packs write OMH-prefixed role files under `~/.hermes/agents`. The
`cto-loop` pack exposes a CTO, PM, Dev, QA, Security, and Ops structure, but it
is not installed by default.

```sh
omh setup --with-plugin
omh doctor
```

The plugin bridge installs `~/.hermes/plugins/omh` and registers metadata-only
status support. Local plugin install or import/register smoke is not proof that
Hermes loaded the plugin, executed code, reviewed a PR, passed CI, or merged.

The installer can also pass these advanced setup choices directly:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_WITH_PLUGIN=1 OMH_PROFILE_PACKS=cto-loop sh
```

## Documentation

| Need | Read |
| --- | --- |
| Full docs map | [Documentation](docs/README.md) |
| Install, update, reapply, uninstall, and installer flags | [Installation](docs/INSTALLATION.md) |
| AI-agent pasteable install protocol | [Agent Install](INSTALL_FOR_AGENTS.md) |
| Product direction and boundaries | [Direction](docs/DIRECTION.md) |
| Architecture and module ownership | [Architecture](docs/ARCHITECTURE.md) |
| Situation playbooks | [Playbooks](docs/PLAYBOOKS.md) |
| Role surfaces and profile packs | [Roles](docs/ROLES.md) |
| Memory/context review and handoff packs | [Memory Context Review](docs/MEMORY_CONTEXT.md) |
| Discord-style wrapper examples | [Chat Wrapper Examples](docs/CHAT_WRAPPER_EXAMPLES.md) |
| Harness quality contracts | [Harness Quality Contract](docs/HARNESS_QUALITY.md) |
| Representative workflows | [Application Cases](docs/APPLICATION_CASES.md) |
| Public website source | [GitHub Pages site](site/index.html) |

## Development

Install the current checkout in editable mode:

```sh
python3 -m pip install -e .
```

Run the core checks:

```sh
python3 -m unittest discover -s tests
python3 -m compileall src
python3 -m omh.cli docs workflows --check
python3 -m omh.cli harness validate
python3 -m omh.cli release hermes-smoke
```

Smoke-test setup without touching real home directories:

```sh
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --dry-run
```

Before a release candidate, run the live Hermes profile smoke from the target
operator profile. The tap smoke uses the same full identifier install path:

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
```

OMH 1.0.0 is a quality-gated stable baseline. Richer profile activation probes
and more artifact-backed wrapper examples are tracked in the roadmap and
release docs.
