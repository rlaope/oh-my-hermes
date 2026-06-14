# oh-my-hermes

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
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

**oh-my-hermes** makes Hermes Agent feel more capable after install. OMH
adds workflow skills, optional profiles, wrapper-facing contracts, local
evidence records, and coding/runtime handoff preparation while keeping normal
users in Hermes chat.

The product is not "more CLI commands." The `omh` command is bootstrap,
doctor, verifier, and wrapper/backend infrastructure. For Hermes wrappers and
routers, that CLI contract is a first-class backend surface; for normal users,
the main experience is:

```text
user says a plain request in Hermes
  -> OMH routes it to the right skill/playbook/profile
  -> Hermes explains the next action and evidence boundary
  -> coding is handed off to the selected runtime only when the user or wrapper accepts that path
```

> Have you ever felt that Hermes Agent is powerful, but still has a high
> barrier to entry? OMH exists for that gap between installation and real use:
> setup, config checks, verification, workflow choice, and the first useful
> task. The engine is already strong across Skills, Gateway, Profiles, and
> Cron; OMH adds a thin practical layer of ready-to-use workflows such as
> `web-research`, `doctor`, `idea-to-deploy`, `ultragoal`, `loop`, and
> `ultraprocess` so Hermes can
> feel easier to start, easier to trust, and more natural to apply in real
> work.

[Website](https://rlaope.github.io/oh-my-hermes/) -
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
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

Terminal setup output supports English, Korean, Japanese, and Chinese:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_LANG=ko sh
omh setup --language ko
```

The installer normally runs setup for you. Keep `omh setup` in the quick start
because it is the repeatable repair step that installs generated skills under
`~/.omh/skills` and registers them with Hermes through `skills.external_dirs`.
When you run it in a real terminal, `omh setup` opens a small colored wizard for
the setup language, install scope, Hermes registration, the default coding
handoff style, optional MCP bridge preference, and optional visible team role
presets. It also installs the lightweight Hermes plugin bridge so local OMH
status context is available when Hermes supports it. All OMH workflows are
installed either way. Non-interactive shells use the safe defaults. Add `--json`
when an operator or wrapper needs the full machine-readable payload.

The default user scope installs under `~/.omh` and `~/.hermes`. Use project
scope when a repository should carry its own isolated OMH/Hermes setup:

```sh
omh setup --scope project
omh --scope project doctor
```

Verify the local install:

```sh
omh doctor
```

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
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

Use the full identifier above for the first install. It avoids short-name
resolver ambiguity in current Hermes CLI releases and still installs the
`oh-my-hermes` skill.

For pinned releases after a matching `v<version>` tag exists:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

For preview updates before the next release, rerun the same installer. If your
release automation knows the commit SHA, pass it as `OMH_SOURCE_REF=main@<sha>`
so OMH can display and record `main@old -> main@new` instead of only `main`.

## Why OMH

<p align="center">
  <img src="assets/omh-flagship-workflows-poster.png" alt="OMH flagship command sets poster" width="920">
</p>

- **Natural-language first** - users in chat do not need to know `omh` commands.
- **Install-first, not dashboard-first** - get Hermes-visible skills without
  adopting a separate dashboard or app.
- **Hermes-native boundary** - OMH extends Hermes Agent with skills,
  workflows, plugin context, and local evidence contracts.
- **Runtime-aware coding** - coding-heavy requests become prepared handoffs
  for the selected path: Codex lifecycle, Claude Code or generic prompt
  handoff, or Hermes/OMX/OMO/OMC runtime handoff with team/swarm,
  worker-protocol, and worktree guidance.
- **Wrapper-native executor sessions** - after a handoff is ready, Hermes chat
  surfaces can render buttons such as Open in Codex, Open in Claude Code,
  Attach session, Refresh status, Record completed, Record blocked, and Ask
  Hermes to verify. The user does not need to type backend commands.
- **Operating model defaults** - a solo operator, small team, research ops, or
  coding runtime team can be recorded during setup so Hermes starts from the
  right collaboration posture without forcing visible role files.
- **Evidence-aware status** - prepared, dispatched, executed, reviewed,
  verified, CI, and merge-ready states stay separate.
- **Observed runtime ledger** - runtime starts, worktree creation, worker
  dispatch/results, verification, review, CI, merge-readiness, and merge claims
  are separate `runtime_observation/v1` records instead of prose guesses.
- **Durable goal mode contracts** - long work can stay tied to `.omh/goals`
  ledgers, completion gates, and explicit "continue/checkpoint/block/complete"
  next actions instead of ending with a vague summary.
- **Loop runtime ticks** - ambitious `./loop` goals can be advanced by a local
  tick or `omh loop run-once` with a deterministic queue shape for worktree,
  subagent, connector, handoff, and `verification_plan` metadata plus a
  `loop_engineering/v1` snapshot over automation, worktree, skill, connector,
  subagent, inner-loop checks, outer-loop checks, and verifier policy. Hermes
  can show the queue, prepare the next handoff, warn about verification gaps,
  comprehension debt, or cognitive surrender, then mark the item observed or
  blocked without pretending those steps already ran. The `run-once` result
  explicitly reports whether it created a tick or found an existing pending
  queue item.
- **Local and inspectable** - skills, manifests, plans, sessions, and runtime
  records live in user-owned local directories.

## Flagship Command Sets

| Representative workflow | Boundary | Plain request |
| --- | --- | --- |
| `deep-interview` / `ralplan` / `ultragoal` / `loop` / `ultraprocess` | Hermes turns ambiguous intent into a concrete goal, plan, execution-ready path, direct ambitious goal loop, or one PR-ready delivery cycle. | "Make onboarding feel smoother." |
| `feedback-triage` / `research-brief` / `strategy-brief` | Hermes keeps non-coding company and product operations inside brief, evidence, and decision workflows. | "Payment failures keep coming up." |
| `operating-rhythm` / `report-package` / `reliability-review` | Hermes records operating cadence, report packages, and reliability reviews as separate local artifacts with strict evidence boundaries. | "Turn the sprint retro, monthly report, and incident review into durable records." |
| `idea-to-deploy` / coding runtime handoff / executor selection | Hermes prepares work for Codex, Claude Code, another coding agent, an oh-my runtime, or Hermes coding skills without hiding unobserved execution. | "Turn this issue into a PR-ready plan and hand it to implementation." |

## What You Get

| Surface | What it provides |
| --- | --- |
| Hermes skill tap | Tap-compatible skills under `skills/<name>/SKILL.md`. |
| Bootstrap setup | `omh setup` installs generated skills and registers `skills.external_dirs` in user or project scope. |
| Flagship playbook | `request-to-handoff` turns a plain Hermes message into a role-owned next action with an evidence boundary. |
| App operation loops | `idea-to-deploy`, `cto-loop`, and `deploy-and-monitor` make Hermes feel like an app delivery operator while keeping evidence boundaries strict. |
| Ambitious goal loops | `loop` lets Hermes run a direct high-level goal cycle across task discovery, distribution, execution, verification, next-task decisions, runtime tick queueing, handoff, feedback, waiting, and resume states inside an explicit permission profile. Start cards, `loop_engineering/v1` snapshots, `loop_status_card/v1` failure-mode warnings, and queue lifecycle actions help wrappers show what can start, what is only prepared, what verification is cheap or expensive, and what was later observed or blocked. |
| PR-ready delivery process | `ultraprocess` is Ultra Process: Research -> Ralplan -> Ultragoal -> Code Review -> Sync Circle, one PR-ready delivery cycle without claiming unobserved executor work. Use `loop` instead when the goal should keep repeating after feedback. |
| Business workflows | Research briefs, strategy briefs, meeting briefs, feedback triage, and ops review for non-coding company work. |
| Operations artifacts | `omh ops rhythm`, `omh ops report`, and `omh ops reliability` create schema-versioned local records under `.omh/operations`. `omh ops list` is summary-only and bounded by default; `omh ops export` returns Markdown or JSON outlines for wrapper/report use; binary PPTX export is intentionally a separate observed step. |
| Coding handoffs | Executor/runtime-neutral handoff payloads with acceptance, review, verification, team/swarm, worker-protocol, and worktree expectations. |
| Runtime observation ledger | `omh runtime observe` records what a wrapper or operator actually observed for Hermes/OMX/OMO/OMC runtime handoffs without upgrading missing steps into evidence. |
| Memory context review | Review OMH-local and wrapper-supplied context, flag stale assumptions, and attach conflict-free summaries to executor handoffs. |
| Strict goal progress | `.omh/goals` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, and `goal_continuation/v1` keep long-running goals from being treated as done before evidence is ready. |
| Hermes chat contracts | `chat_interaction/v1`, status cards, action ids, and local runtime artifacts for Hermes Agent chat surfaces. |
| Hermes plugin bridge | `omh setup` installs `~/.hermes/plugins/omh` with metadata-only `omh_hud` and `omh_status` support. |
| Optional MCP bridge preference | `omh setup --with-mcp` records MCP bridge intent without claiming a host loaded or called it; `omh probe` separates `mcp_preference` from `mcp_host_config`. |
| Parity verifier | `omh probe --parity` maps common oh-my runtime capability axes to OMH surfaces, gaps, and evidence boundaries. |
| Operating models | `omh setup --operating-model <id>` records the default Hermes collaboration posture: solo operator, small team, research ops, or coding runtime team. |
| Optional team profile packs | CTO/PM-style or delivery/research role files can be installed only when selected. |

## How It Feels In Hermes

| Plain user message | OMH-shaped Hermes behavior |
| --- | --- |
| "Payment failures keep coming up." | Route to feedback triage or investigation first; prepare reproduction and evidence needs before coding. |
| "Can this issue become a PR?" | Convert the issue into a plan, acceptance criteria, verification commands, and an executor/runtime-neutral handoff. |
| "Prepare next week's strategy meeting." | Use research, meeting, and strategy skills without defaulting to implementation. |
| "Keep meeting minutes, scrum notes, sprint plans, and retros in one history." | Use `operating-rhythm` to prepare or record a durable cadence artifact with decisions and follow-up actions separated from unobserved outcomes. |
| "Create a monthly leadership PPT report package." | Use `report-package` to prepare a clean report or slide outline without requiring SRE evidence or claiming a binary deck was exported. |
| "Run a postmortem, SLO, and error-budget reliability review." | Use `reliability-review` to require metric, incident, or source references before reliability claims advance. |
| "Take this idea from plan to deploy and monitor it safely." | Shape the idea, record decision gates, prepare an executor handoff only if code is accepted, then track release/deploy/monitor status separately. |
| "Run a CTO loop for roadmap and release readiness." | Structure PM, architecture, delivery risk, release readiness, and follow-up decisions without forcing hidden role agents. |
| "./loop make this a 10k-star quality OSS." | Show a start card for permission and executor choice, preserve the large goal, expose the loop pipeline and automation/worktree/skill/connector/subagent/verification state, queue one prepared step with inner or outer verification intent, warn on verification gaps or comprehension debt, then record whether each item was observed or blocked. |
| "Deploy and monitor this release with rollback checks." | Show release scope, go/no-go, health signals, rollback gate, and post-deploy status without claiming infrastructure execution. |
| "This refactor feels risky." | Produce a bounded plan, risk notes, review expectations, and a selected-runtime coding handoff only after acceptance. |
| "Are we ready to release?" | Separate prepared claims from observed test, review, CI, and merge-readiness evidence. |

For company and app operation work, OMH can help Hermes classify, brief, record,
decide, handoff, and track the next workflow without pretending data was
fetched, a meeting happened, code was implemented, a report was approved, a
binary deck was exported, or a deployment was observed.

## Profiles And Plugin

Setup installs the skill layer and the thin metadata-only plugin bridge by
default. Operators can still opt into visible role profile packs when the target
Hermes environment benefits from them.

```sh
omh profile list
omh profile inspect coding-runtime-team
omh setup --operating-model coding-runtime-team
omh profile inspect cto-loop
omh setup --profile-pack cto-loop
```

Operating models are routing and narration defaults. They do not install role
files by themselves. For example, `coding-runtime-team` makes runtime handoff
templates and observed runtime status feel first-class, while `research-ops`
keeps Hermes biased toward research, strategy, and meeting workflows.

Profile packs write OMH-prefixed role files under `~/.hermes/agents`. The
`cto-loop` pack exposes a CTO, PM, Dev, QA, Security, and Ops structure, but it
is not installed by default.

The plugin bridge installs `~/.hermes/plugins/omh` and registers metadata-only
HUD/status support. `omh hud` prints the same compact line a Hermes TUI or
status surface can render, for example
`[omh] v1.0.0 | plugin:ready | target:single | coding-agent:idle(ask)`.

For coding runtime handoffs, wrappers can record observed steps without claiming
that missing steps happened:

```sh
omh coding delegate --executor omx-runtime "risky refactor"
omh runtime observe --session <session-id> --runtime-profile omx-runtime --event runtime_start --summary "operator started runtime"
```

`--runtime-profile` must match the prepared runtime handoff on that wrapper
session. Prompt-only and Codex lifecycle sessions report runtime observation as
not applicable instead of asking for a fake runtime ladder.

For chat users, this normally appears as a status card and buttons rather than
manual commands:

```text
Hermes: A coding-agent handoff is ready.
Buttons: Open in Codex | Attach existing session | Refresh status
Status: Coding agent is prepared in Codex.
        Executor session is not attached yet.
        Handoff is ready.
        Dispatch/open has not been observed yet.
        Executor result has not been observed yet.
        Hermes verification has not been requested yet.
```

When a wrapper observes a button action or external executor session, it records
`executor_session/v1` metadata under the wrapper session. That can update the
status to `coding-agent: running(codex)` or `completed(claude-code)` without
claiming review, CI, merge readiness, or merge.

The status card will still show worktree creation, worker dispatch, worker
result, verification, review, CI, and merge as missing until matching
`runtime_observation/v1` records exist.
When runtime evidence exists, the line can show states such as
`coding-agent:prepared(codex)` and `evidence:prepared_not_observed`. HUD is
intentionally small: version, plugin status, target topology, current or
default coding agent, and evidence state. Host-supplied token metadata stays in
the machine-readable payload but is not shown in the Hermes-facing status line.
Skill inventory and deep diagnostics belong in `omh doctor`,
`omh_status`, or machine-readable setup output, not the status line. Local
plugin install or import/register smoke is not proof that Hermes loaded the
plugin, executed code, reviewed a PR, passed CI, or merged.

The installer can also pass these advanced setup choices directly:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_SCOPE=project OMH_WITH_MCP=1 OMH_PROFILE_PACKS=cto-loop sh
```

## Documentation

| Need | Read |
| --- | --- |
| Full docs map | [Documentation](docs/README.md) |
| Install, update, reapply, uninstall, and installer flags | [Installation](docs/INSTALLATION.md) |
| AI-agent pasteable install protocol | [Agent Install](INSTALL_FOR_AGENTS.md) |
| Product direction and boundaries | [Direction](docs/DIRECTION.md) |
| Architecture and module ownership | [Architecture](docs/ARCHITECTURE.md) |
| Common oh-my runtime parity and gaps | [Parity Matrix](docs/PARITY.md) |
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
python3 -m omh.cli release checklist --json
python3 -m omh.cli release hermes-smoke
omh --help
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --install-path setup --omh-command omh --include-command-smoke
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
