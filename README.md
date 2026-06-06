# oh-my-hermes-agent

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes Agent" width="720">
</p>

<p align="center">
  <strong>Hermes-native workflow skills, installed with one small command.</strong>
  <br>
  <em>Give Hermes Agent a consistent skill pack for routing, planning, durable execution, review, cleanup, and QA.</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-quality--gated%20preview-blue">
</p>

**oh-my-hermes-agent** installs a Hermes-native workflow layer for routing,
planning, chat-wrapper UX, evidence tracking, and coding handoff preparation.

Hermes stays the chat-facing agent. OMHM adds deterministic local contracts
around it so Discord, Slack, hosted wrappers, and local operators can turn a
plain user message into a clear next step: answer, clarify, research, plan,
delegate coding, or report status.

[Quick Start](#quick-start) - [Command Surface](#command-surface) -
[Wrapper Flow](#wrapper-flow) - [Documentation](docs/README.md) -
[Installation](docs/INSTALLATION.md) - [Application Cases](docs/APPLICATION_CASES.md)

---

## Why OMHM

- **Natural-language first** - users in chat do not need to know `omh` commands.
- **Hermes-native boundary** - no Hermes core patching, hidden transport bot, or
  network service inside this package.
- **Delegation-first coding** - coding-heavy requests become prepared handoffs
  for external coding executors, with review and verification expectations.
- **Evidence-aware status** - prepared, dispatched, executed, reviewed,
  verified, CI, and merge-ready states stay separate.
- **Local and inspectable** - skills, manifests, plans, sessions, and runtime
  records live in user-owned local directories.

## What You Get

| Surface | What it provides |
| --- | --- |
| Managed skills | Generated Hermes skill guidance under `~/.omh/skills`. |
| Local installer | Reversible install, update, apply, doctor, and uninstall commands. |
| Skill catalog | Deterministic routing metadata from `src/skills/catalog.py`. |
| Harness quality | Machine-readable quality bars, evidence ladders, wrapper actions, and overclaim guards. |
| Wrapper contract | `chat_interaction/v1` responses for Discord, Slack, and hosted adapters. |
| Planning artifacts | Hermes-facing Markdown plans under `~/.hermes/plans`. |
| Coding handoffs | Prepared executor payloads with acceptance, review, and verification expectations. |
| Runtime evidence | Metadata-only run/session records under `~/.omh/runtime`. |

## Quick Start

**Step 1: Install**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
```

**Step 2: Verify**

Most users should start with one health check:

```sh
omh doctor
```

Then open Hermes Agent and use the installed skills through Hermes' normal skill
surfaces.

**Step 3: Try one wrapper-shaped turn**

```sh
omh chat interact --source discord "risky refactor"
```

That returns a `chat_interaction/v1` JSON envelope a Discord, Slack, or hosted
adapter can render without exposing shell commands to the end user.

### Stable Install

The default installer target is the preview channel from `main`. For a pinned
stable install, use a tagged release:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=0.1.0 sh
```

### Updating

```sh
omh update
omh apply
omh doctor
```

## Mental Model

OMHM is a local contract layer around Hermes, not a replacement runtime.

```text
User chat
  -> Discord, Slack, or hosted wrapper
  -> omh chat interact
  -> Hermes skill guidance, plan, status, or coding handoff
  -> external executor only when coding work is accepted
  -> observed evidence recorded back into local runtime artifacts
```

`omh apply` updates only Hermes' `skills.external_dirs` registration. It does
not rewrite workspace instructions or modify Hermes internals.

## Wrapper Flow

Wrappers should treat `omh chat interact` as the primary API.

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

## What Gets Recorded

`omh` records runtime metadata only by default:

- install/apply/doctor summaries in `~/.omh/runtime/state.json`
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
not open network connections, authenticate bots, post messages, invoke Codex, or
patch Hermes internals.

Hermes plans include a deterministic `quality_gate` and `deep_interview`
contract. Blocked plans ask one concise question; draft plans remain unapproved
until the wrapper or user accepts them.

## Command Surface

Root README intentionally shows the small public surface. Lower-level runtime
and debug commands remain available, but they are documented in focused guides
instead of presented as the first path.

| Need | Command |
| --- | --- |
| Install | `curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh \| sh` |
| Verify | `omh doctor` |
| Update | `omh update && omh apply && omh doctor` |
| Inspect installed skills | `omh list` |
| Pick a workflow locally | `omh recommend <task>` |
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
| Harness quality contracts | [Harness Quality Contract](docs/HARNESS_QUALITY.md) |
| Representative workflows | [Application Cases](docs/APPLICATION_CASES.md) |
| Generated workflow catalog | [Workflow Reference](docs/WORKFLOWS.md) |

## Development

Install the current checkout in editable mode:

```sh
python -m pip install -e .
```

Run the test suite:

```sh
python -m unittest discover -s tests
python -m compileall src
```

Smoke-test the installer without touching real home directories:

```sh
python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke install --dry-run
```

## Roadmap

This repository is a quality-gated preview. Current work focuses on making
Hermes-side chat orchestration feel complete while keeping execution claims
evidence-backed and local.

- Versioned release artifacts for stable installer targets
- A richer generated routing registry
- More artifact-backed bot and workflow examples
- More Hermes-specific diagnostics in `omh doctor`
- Workflow fixtures that verify generated skill behavior remains conservative
