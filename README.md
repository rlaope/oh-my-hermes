# oh-my-hermes-agent

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes Agent" width="720">
</p>

<p align="center">
  <strong>Install once. Talk to Hermes. Let OMHM shape the work.</strong>
  <br>
  <em>Hermes-native skills, optional team profiles, wrapper contracts, evidence status, and executor-ready handoffs.</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-quality--gated%20preview-blue">
</p>

**oh-my-hermes-agent** makes Hermes Agent feel more capable after install. It
adds workflow skills, optional team/profile packs, wrapper-facing contracts,
local evidence records, and coding handoff preparation while keeping normal
users in Hermes chat.

The product is not "more CLI commands." The `omh` command is bootstrap,
doctor, verifier, and wrapper/backend infrastructure. The main experience is:

```text
user says a plain request in Hermes
  -> OMHM routes it to the right skill/playbook/profile
  -> Hermes explains the next action and evidence boundary
  -> coding is handed off only when the user or wrapper accepts that path
```

[Website](https://rlaope.github.io/oh-my-hermes-agent/) -
[Quick Start](#quick-start) - [Two Install Paths](#two-install-paths) -
[Role Model](#role-model) -
[Backend Surface](#backend--operator-surface) - [Documentation](docs/README.md) -
[Installation](docs/INSTALLATION.md) - [Agent Install](INSTALL_FOR_AGENTS.md) -
[Roles](docs/ROLES.md) - [Application Cases](docs/APPLICATION_CASES.md)

---

## Why OMHM

- **Natural-language first** - users in chat do not need to know `omh` commands.
- **Install-first, not dashboard-first** - get a Hermes-visible skill layer
  without adopting a hosted service, bot SDK, or separate app.
- **Hermes-native boundary** - no Hermes core patching, hidden transport bot, or
  network service inside this package.
- **Optional team profiles** - provide CTO/PM-style or research/strategy
  operating models when the operator wants them; do not force them by default.
- **Delegation-first coding** - coding-heavy requests become prepared handoffs
  for the selected executor: Codex lifecycle when supported, or prompt-only
  handoff for Claude Code, OMHM-style runtime users, generic agents, or Hermes.
- **Evidence-aware status** - prepared, dispatched, executed, reviewed,
  verified, CI, and merge-ready states stay separate.
- **Local and inspectable** - skills, manifests, plans, sessions, and runtime
  records live in user-owned local directories.

## How It Feels In Hermes

After setup, the normal surface is still Hermes chat. OMHM gives Hermes a
stronger operating model for deciding what kind of work a message is asking
for, which skill should own the next step, and what has actually been observed.

| Plain user message | OMHM-shaped Hermes behavior |
| --- | --- |
| "Payment failures keep coming up." | Route to feedback triage or investigation first; prepare reproduction and evidence needs before coding. |
| "Can this issue become a PR?" | Convert the issue into a plan, acceptance criteria, verification commands, and an executor-neutral handoff. |
| "Prepare next week's strategy meeting." | Use research, meeting, and strategy skills without defaulting to implementation. |
| "This refactor feels risky." | Produce a bounded plan, risk notes, review expectations, and a coding-agent handoff only after acceptance. |
| "Are we ready to release?" | Separate prepared claims from observed test, review, CI, and merge-readiness evidence. |

The CLI exists so operators, wrappers, and CI can install, verify, replay, and
inspect those contracts. It is not the daily UX for a normal Hermes user.

## What You Get After Install

| Surface | What it provides |
| --- | --- |
| Hermes skill tap | Tap-compatible skills under `skills/<name>/SKILL.md` for Hermes-native install. |
| Bootstrap setup | `omh setup` installs the same generated skills under `~/.omh/skills` and registers `skills.external_dirs`. |
| Optional Hermes plugin | `omh setup --with-plugin` installs a thin native bridge under `~/.hermes/plugins/omhm`. |
| Skill catalog | Deterministic routing metadata from `src/skills/catalog.py`. |
| Business workflow skills | `research-brief`, `strategy-brief`, `meeting-brief`, `feedback-triage`, and `ops-review` for non-coding company work inside Hermes. |
| Flagship playbook | `request-to-handoff` turns a plain Hermes message into a role-owned next action with an evidence boundary. |
| Playbooks | Situation-level pipelines for research, meetings, strategy, feedback triage, ops review, planning, wrapper UX, and coding handoff flows. |
| Role surface | `research-lead`, `planning-lead`, `review-gate`, and `coding-handoff` describe responsibility lanes, not hidden runtime agents. |
| Optional team profile packs | `startup-delivery`, `engineering-delivery`, `research-strategy`, and `cto-loop` can install Hermes agent role files only when selected. |
| Harness quality | Machine-readable quality bars, evidence ladders, wrapper actions, and overclaim guards. |
| Wrapper backend contract | `chat_interaction/v1` responses for Discord, Slack, and hosted adapters. |
| Planning artifacts | Hermes-facing Markdown plans under `~/.hermes/plans`. |
| Coding handoffs | Prepared executor payloads with acceptance, review, and verification expectations. |
| Runtime evidence | Metadata-only run/session records under `~/.omh/runtime`. |

Think of this as three layers:

1. **Hermes-facing skills and profiles** for the user-facing conversation.
2. **Local contracts and artifacts** so wrappers can render buttons, status,
   plans, and handoffs without guessing.
3. **Operator commands** for install, doctor, smoke tests, and evidence checks.

## Role Model

OMHM installs **skills and contracts first**. Team/profile packs are available,
but they are opt-in.

That is intentional. Hermes users may be solo maintainers, startup founders,
PMs, researchers, support operators, agencies, or engineering teams. Some want
a CTO/PM/Dev/QA/Ops style loop; others just want Hermes to turn a plain message
into the right next workflow without adopting a full organization metaphor.

What exists today:

| Layer | Exists today | Meaning |
| --- | --- | --- |
| Responsibility roles | Yes | `research-lead`, `planning-lead`, `review-gate`, and `coding-handoff` explain who owns the next action in chat. |
| Hermes skills | Yes | Generated `skills/<name>/SKILL.md` files are installable through Hermes tap or `omh setup`. |
| Optional plugin bridge | Yes | `omh setup --with-plugin` installs a thin metadata/status bridge under `~/.hermes/plugins/omhm`. |
| Optional team profile packs | Yes, opt-in | `omh setup --profile-pack <id>` writes OMHM-prefixed Hermes agent role files under `~/.hermes/agents`. |

This keeps the default install broad and low-commitment:

```text
plain request -> request-to-handoff -> responsible role -> next action -> evidence boundary
```

A CTO/PM-style structure is a good **optional profile pack**, not the default
product surface. OMHM provides selectable packs:

- `startup-delivery`: Product Lead, Tech Lead, QA Gate, Release Lead
- `engineering-delivery`: Planning Lead, Coding Handoff, Review Gate, Release Gate
- `research-strategy`: Research Lead, Strategy Lead, Meeting Lead
- `cto-loop`: CTO, PM, Dev, QA, Security, Ops

Inspect and install them with:

```sh
omh profile list
omh profile inspect cto-loop
omh setup --profile-pack cto-loop
```

Installing a pack writes role files such as
`~/.hermes/agents/omhm-cto-loop-cto.md`. It does not prove Hermes activated the
profile, spawned an agent, executed code, reviewed a PR, passed CI, or merged
anything. Those claims still require observed runtime or wrapper evidence.

## Quick Start

**Step 1: Install OMHM and apply the Hermes setup**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
```

The installer normally runs setup for you. Keep `omh setup` in the quick start
because it is the repairable, repeatable step that installs generated skills
under `~/.omh/skills` and registers them with Hermes through
`skills.external_dirs`.

Optionally verify the local install:

```sh
omh doctor
```

If your Hermes environment supports native skill taps, this is the equivalent
Hermes-native front door:

```sh
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install oh-my-hermes
```

You can skip this next block. It is only for operators who want individual
workflow shortcuts exposed directly in Hermes:

```sh
hermes skills install deep-interview
hermes skills install ralplan
hermes skills install web-research
hermes skills install feedback-triage
hermes skills install ops-review
hermes skills install code-review
```

**Step 2: Talk to Hermes**

Send the flagship first prompt in Hermes Agent, Discord, Slack, or a hosted
Hermes wrapper:

```text
Use OMHM request-to-handoff for: I want to safely add a feature to this repo.
```

Hermes should explain why `request-to-handoff` is the right first workflow,
name the responsible role, show the next action, and say what is not evidence
yet. Users should not need to know `omh recommend`, `omh chat interact`, or
other backend commands.

For non-coding company work, the same install can route prompts such as:

```text
결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘
prepare weekly ops review from customer feedback and release risks
we need a competitor market scan and strategy memo for next week's leadership meeting
```

Those stay Hermes-retained by default. OMHM can classify, brief, and record the
next workflow without pretending data was fetched, a meeting happened, or a
coding executor implemented anything.

**Step 3: Add a team profile only when you want one**

Most users can skip this. If the operator wants an explicit CTO/PM/QA/Ops or
research/strategy operating model, inspect the available packs and opt in:

```sh
omh profile list
omh setup --profile-pack startup-delivery
omh setup --profile-pack cto-loop
```

Profile packs are Hermes role files, not hidden automation. They make the chat
operating model easier to understand, while OMHM still keeps execution,
review, CI, and merge claims evidence-gated.

## Two Install Paths

### Path A: Hermes-native skill install

Use this when Hermes skill taps are available in the target environment. It is
the cleanest user-facing path because Hermes sees OMHM as installed skills:

```sh
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install oh-my-hermes
```

This installs from the repo's tap-compatible `skills/` directory and keeps the
main UX inside Hermes.

### Path B: OMHM bootstrap setup

Use this when you want a Python installer, repair command, generated managed
skills, local doctor checks, or wrapper/backend commands:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
omh doctor
```

`omh setup` installs generated skills under `~/.omh/skills` and registers that
directory through Hermes' `skills.external_dirs`. The intended final state is
the same from the user's point of view: Hermes sees OMHM skills, and the user
talks to Hermes.

**Optional native plugin bridge**

```sh
omh setup --with-plugin
omh doctor
```

This installs a small `~/.hermes/plugins/omhm` bundle that registers an
`omhm_status` tool and a passive `pre_llm_call` status-context hook. It is
operator opt-in: skills remain the default user-facing surface, and Hermes may
still require its own plugin enable/reload step before the bundle is used.
Local plugin import/register smoke is not proof that Hermes loaded the plugin.

**Optional operator smoke test**

```sh
omh chat interact --source discord "I want to safely add a feature to this repo"
```

That returns a `chat_interaction/v1` JSON envelope a Discord, Slack, or hosted
adapter can render without exposing shell commands to the end user.

**Optional local demo**

```sh
omh demo orchestration
```

The demo is deterministic and transport-free. It shows the full
recommend -> chat response -> Hermes plan -> selected executor handoff -> status
card path without calling an LLM, bot SDK, network API, or Hermes core patch.

**Optional playbook inspection**

```sh
omh playbook recommend "I want to safely add a feature to this repo"
```

Playbooks are backend/operator contracts that describe the wrapper-visible
pipeline for situations such as source-backed research, research-to-strategy
briefs, meeting prep, feedback triage, weekly ops review, safe feature change,
release-readiness review, and local pipeline buildout.

**Optional team profile pack**

```sh
omh profile list
omh profile inspect cto-loop
omh setup --profile-pack cto-loop
```

This creates OMHM-prefixed role files under `~/.hermes/agents`. It is useful
when the operator wants Hermes to speak in an organization-style structure such
as CTO, PM, Dev, QA, Security, and Ops. It is not installed by default.

### Stable Install

The default installer target is the preview channel from `main`. For a pinned
stable install, use a published release tag:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

Replace `<version>` with a released version after the matching `v<version>` tag
exists.

### Updating

```sh
omh update
omh setup
omh doctor
```

## Mental Model

OMHM is a local contract layer around Hermes, not a replacement runtime.

```text
User chat
  -> Hermes Agent with installed OMHM skills
  -> optional Discord, Slack, or hosted wrapper
  -> optional OMHM backend contract for buttons, plans, handoffs, and status
  -> external executor only when coding work is accepted
  -> observed evidence recorded back into local runtime artifacts
```

`omh apply` updates only Hermes' `skills.external_dirs` registration. It does
not rewrite workspace instructions or modify Hermes internals.

## Wrapper Backend Flow

Wrappers can treat `omh chat interact` as their local backend API. End users
should see Hermes chat responses, buttons, threads, and status cards, not shell
commands.

1. Receive a natural-language user message.
2. Call `omh chat interact` with a platform source and message or event JSON.
3. Render `chat_response.headline`, `body`, `state`, `actions`, and
   `status_card` when present.
4. Wait for clarification, plan acceptance, revision, cancellation, or handoff
   action.
5. If coding is accepted, dispatch the prepared handoff to an external coding
   executor outside OMHM.
6. Record only observed progress back into the lifecycle or runtime evidence
   commands.

The wrapper user sees a normal chat UX. The adapter owns buttons, threads,
message edits, dispatch, and platform credentials.

Source-checkout examples show how a transport shim can render fixture events
without Discord or Slack SDKs:

```sh
uv run python examples/discord-adapter-shim.py
uv run python examples/slack-adapter-shim.py
```

Those shims read JSON under `examples/wrapper-events/` and emit a compact
`wrapper_adapter_shim/v1` render payload with response copy, action ids, and
status card data when present.

## What Gets Recorded

`omh` records runtime metadata only by default:

- setup/install/apply/doctor summaries in `~/.omh/runtime/state.json`
- workflow run envelopes in `~/.omh/runtime/runs/<run-id>/run.json`
- append-only run events in `events.jsonl`
- wrapper chat sessions in `~/.omh/runtime/wrapper_sessions/<session-id>/`
- delegation observation in `delegation.json`
- prepared coding handoffs in `coding_delegation.json`
- wrapper observation in `wrapper.json`
- review, CI, and merge evidence in `review.json`, `ci.json`, and
  `merge.json`

Prepared handoff is never treated as implementation, review, CI, or merge
evidence by itself. If the wrapper cannot prove that a step happened, status
should stay `prepared_not_observed`, `not_observed`, or `not_available`.
Status readers evaluate the full run ledger conservatively: a later merge-ready
artifact cannot override missing verification, review, or CI evidence.
Wrapper status responses include a `status_card/v1` progress object so adapters
can render handoff, execution, verification, review, CI, merge-ready, and merged
steps without parsing prose.
Workflow and handoff payloads can also include `harness_quality/v1`, which lets
adapters render the lane quality bar, evidence ladder, safe action ids, and
overclaim guards without guessing from generated skill text.
Runtime delegation status also includes `harness_progress/v1`, calculated from
that evidence ladder and observed runtime records.

Inspect and validate the live harness catalog with:

```sh
omh harness list
omh harness inspect coding-handling
omh harness validate
```

## Routing Model

The `oh-my-hermes` skill is the top-level router.

It is prompt-level guidance, not a hidden runtime hook. Explicit skill
invocation wins, strong workflow signals route to catalog-backed skills, broad
planning requests stay in planning first, and ambiguous messages ask one concise
clarification question.

The generated catalog classifies each workflow by role:

| Role | Examples | Default behavior |
| --- | --- | --- |
| Retained cognition | `web-research`, `deep-interview`, `plan`, `ralplan` | Hermes handles clarification, research, planning, and status narration. |
| Handoff guidance | `ultragoal`, `ultrawork`, cleanup workflows | Hermes prepares and tracks coding handoffs instead of implying hidden implementation. |
| Verification | `code-review`, `ultraqa` | Hermes can frame review and QA expectations; code fixes remain executor work. |

Actual Discord and Slack transports stay outside this repository. `omh` does
not open network connections, authenticate bots, post messages, invoke coding
executors, or patch Hermes internals.

Hermes plans include a deterministic `quality_gate` and `deep_interview`
contract. Blocked plans ask one concise question; draft plans remain unapproved
until the wrapper or user accepts them.

## Backend / Operator Surface

The primary product surface is installed Hermes skills. The `omh` command is
support infrastructure for bootstrap, repair, verification, wrapper contracts,
smoke tests, runtime evidence, and operator debugging.

| Need | Command |
| --- | --- |
| Hermes-native install | `hermes skills tap add rlaope/oh-my-hermes-agent && hermes skills install oh-my-hermes` |
| Bootstrap install | `curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh \| sh` |
| Set up or repair managed skills | `omh setup` |
| Verify only | `omh doctor` |
| Update | `omh update && omh setup && omh doctor` |
| Inspect installed skills | `omh list` |
| Pick a workflow locally | `omh recommend <task>` |
| Pick a situation pipeline | `omh playbook recommend <task>` |
| Inspect a pipeline | `omh playbook inspect <id>` |
| List optional team profile packs | `omh profile list` |
| Install a team profile pack | `omh setup --profile-pack cto-loop` |
| Demo wrapper orchestration | `omh demo orchestration` |
| Inspect workflow quality JSON | `omh docs workflows --json` |
| Drive a chat wrapper turn | `omh chat interact <message>` |
| Track delegated coding | `omh coding lifecycle <step>` |
| Summarize observed status | `omh runtime delegation-status --run <run-id>` |
| Remove OMHM | `omh uninstall` |

See [Installation](docs/INSTALLATION.md) for install flags, local skill
fixtures, reapply, wrapper lifecycle, redacted export, and uninstall details.

## Documentation

| Need | Read |
| --- | --- |
| Product direction and boundaries | [Direction](docs/DIRECTION.md) |
| Full docs map | [Documentation](docs/README.md) |
| Install, update, reapply, uninstall | [Installation](docs/INSTALLATION.md) |
| Architecture and module ownership | [Architecture](docs/ARCHITECTURE.md) |
| Delegation lifecycle completeness | [Delegation-First Completeness](docs/DELEGATION_FIRST_COMPLETENESS.md) |
| Situation playbooks | [Playbooks](docs/PLAYBOOKS.md) |
| Discord-style wrapper examples | [Chat Wrapper Examples](docs/CHAT_WRAPPER_EXAMPLES.md) |
| Harness quality contracts | [Harness Quality Contract](docs/HARNESS_QUALITY.md) |
| Representative workflows | [Application Cases](docs/APPLICATION_CASES.md) |
| Generated workflow catalog | [Workflow Reference](docs/WORKFLOWS.md) |
| Public website source | [GitHub Pages site](site/index.html) |

## Development

Install the current checkout in editable mode:

```sh
python3 -m pip install -e .
```

Run the test suite:

```sh
python3 -m unittest discover -s tests
python3 -m compileall src
python3 -m omh.cli docs workflows --check
python3 -m omh.cli harness validate
```

Smoke-test the installer without touching real home directories:

```sh
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --dry-run
```

## Roadmap

This repository is a quality-gated preview. Current work focuses on making
Hermes-side chat orchestration feel complete while keeping execution claims
evidence-backed and local.

- Versioned release artifacts for stable installer targets
- A richer generated routing registry
- Stronger profile-pack activation probes for Hermes environments that expose
  agent/profile lifecycle evidence
- More artifact-backed bot and workflow examples
- More Hermes-specific diagnostics in `omh doctor`
- Workflow fixtures that verify generated skill behavior remains conservative
