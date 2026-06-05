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

## What It Is

`oh-my-hermes-agent` is a local installer and skill pack for Hermes Agent.

It writes managed skills to `~/.omh/skills`, registers that directory in Hermes'
`skills.external_dirs`, and gives Hermes a consistent workflow layer without
patching Hermes core files.

The initial pack includes workflow skills for:

- routing and skill selection
- requirement clarification
- reviewed planning
- durable goal ledgers
- persistent execution loops
- coordinated work lanes
- adversarial QA
- code review
- behavior-preserving cleanup
- research, project notes, cancellation, skill management, and diagnostics

## Status

This repository is a quality-gated preview: small enough to inspect, but shaped
as a real public project instead of a throwaway script.

The current release provides a local installer, generated Hermes skill catalog,
application cases, runtime diagnostics, local runtime artifacts, wrapper-native
chat contracts, CI, and contributor guidance. The next direction is deeper
adapter integration: example Discord/Slack shims, richer routing metadata,
release packaging, and Hermes-specific workflow tests.

## Quick Start

Install and apply the managed Hermes skill pack without cloning the repository:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
```

The default installer target is the preview channel from `main`. For a pinned
stable install, use a tagged release:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=0.1.0 sh
```

Then open Hermes Agent and use the installed skills through Hermes' normal skill
surfaces.

For the full install, Discord bot deployment, update, reapply, and uninstall
flow, see [Installation](docs/INSTALLATION.md).

For reproducible skill-impact examples, see
[Application Cases](docs/APPLICATION_CASES.md).

Check or manage the installation with `omh`:

```sh
omh doctor
omh list
omh runtime status
omh state status
omh update
```

Installer options:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_AUTO_APPLY=0 sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_RUN_DOCTOR=0 sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=0.1.0 sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_PIP_ARGS= sh
```

Useful local and wrapper-debug commands:

```sh
omh install --dry-run
omh install --from-skills-dir ./skills
omh update --from-skills-dir ./skills
omh apply --dry-run
omh recommend "risky refactor"
omh chat interact --source discord "risky refactor"
omh chat interact --source slack --stdin
omh chat route --source discord --record "risky refactor"
omh coding delegate --source discord --record "risky refactor"
omh coding delegate --executor codex --source discord --record "risky refactor"
omh coding lifecycle start --executor codex --record "risky refactor"
omh coding lifecycle report --run <run-id>
omh hermes plan --record "risky refactor with review"
omh runtime record --skill oh-my-hermes --harness coding-handling --status started
omh runtime delegation-status --run <run-id>
omh runtime validate
omh runtime export
omh runtime runs
omh docs workflows
omh probe
omh list
omh snippet --dry-run
omh uninstall
```

## Mental Model

Hermes remains the agent runtime.

`omh` adds six things around it:

1. A managed skill directory at `~/.omh/skills`
2. A manifest at `~/.omh/manifest.json`
3. Local runtime artifacts under `~/.omh/runtime`
4. A config registration in Hermes' `skills.external_dirs`
5. Hermes-facing planning artifacts under `~/.hermes/plans`
6. Platform-neutral chat contracts for Discord, Slack, and hosted wrappers

That means installation is reversible and inspectable. `omh apply` updates only
the Hermes skill discovery setting. It does not rewrite workspace instructions
or modify Hermes internals.

## What Gets Recorded

`omh` records runtime metadata only by default:

- install/apply/doctor summaries in `~/.omh/runtime/state.json`
- workflow run envelopes in `~/.omh/runtime/runs/<run-id>/run.json`
- append-only run events in `events.jsonl`
- delegation observation in `delegation.json`
- prepared coding handoffs in `coding_delegation.json`
- wrapper observation in `wrapper.json`

Hermes-facing plans are separate user-facing Markdown artifacts under
`~/.hermes/plans`. They intentionally include the task statement so Hermes and
the user can inspect the plan subject. They do not store raw platform event JSON
or claim review/execution evidence by default.

Wrapper-native chat interactions are stdout contracts. `omh chat interact`
returns a `chat_interaction/v1` envelope with a renderable
`chat_response/v1` object, platform-neutral actions, a stable `thread_key`, and
an `overclaim_guard`. It does not store raw prompt bodies by default and does
not require the user in Discord or Slack to know any `omh` command names.

Coding delegation artifacts separate a prepared executor handoff from observed
execution. `omh coding delegate --record` stores the recommended workflow,
harness, acceptance criteria, verification expectations, source references,
recommendation evidence, `message_sha256`, `message_length`, and status
`prepared_not_observed`; it does not store the raw prompt body by default. Its
companion `run.json` is bookkeeping for that prepared handoff and is marked
`status: prepared`,
`artifact_kind: prepared_coding_delegation`, `phase: prepared`, and
`observation_status: prepared_not_observed`.

For delegation-first coding flows, wrappers can request an explicit Codex
handoff without asking `omh` to execute Codex:

```sh
omh coding delegate --executor codex --source discord --record "risky refactor"
```

The stdout and runtime record include a `coding_executor_handoff/v1` instruction
payload with executor target `codex`, acceptance criteria, verification
expectations, review expectations, and status `prepared_not_observed`. The raw
message remains a `{message}` placeholder in templates unless
`--include-message` is used for stdout-only wrapper dispatch.

Delegation artifacts separate `requested` from `observed`. If Hermes or a bot
wrapper cannot prove that a specialist lane actually ran, the result should stay
`not_observed` or `not_available`.

Bot wrappers can also record what they actually observed:

```sh
omh runtime wrapper --run <run-id> --prompt-dispatched --response-observed --completion-status completed
omh runtime validate --run <run-id>
omh runtime export --redacted
```

To turn recorded evidence into a safe user-facing status, wrappers can ask for a
deterministic summary:

```sh
omh runtime delegation-status --run <run-id>
```

The summary reports prepared handoff, executor observation, verification
observation, review readiness, a `next_action`, and an `overclaim_guard`.
Prepared handoff is never treated as implementation, review, CI, or merge
evidence by itself.

For Codex-oriented coding work, wrappers can use a higher-level lifecycle
helper instead of stitching together runtime commands by hand:

```sh
omh coding lifecycle start --executor codex --record "risky refactor"
omh coding lifecycle dispatch --run <run-id>
omh coding lifecycle result --run <run-id> --result completed
omh coding lifecycle verify --run <run-id> --completion-status completed
omh coding lifecycle report --run <run-id>
```

The lifecycle helper still writes the same local runtime artifacts. It derives
status from prepared handoff, dispatch observation, executor result,
verification, and review readiness; it does not mutate the prepared run envelope
into proof of execution.

## Routing Model

The `oh-my-hermes` skill is the top-level router.

It is prompt-level guidance, not a hidden runtime hook. When Hermes exposes
installed skill descriptions to the model, the router gives Hermes a clear
registry of workflow names, strong trigger phrases, conservative fallback rules,
and recovery steps.

Routing priority:

1. Explicit slash skill invocation wins.
2. Strong workflow keywords route to the matching installed skill.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in `oh-my-hermes` and ask one concise
   clarification question.

A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when
it could mean normal conversation.

The primary wrapper API is `omh chat interact`. A Discord, Slack, or hosted
Hermes adapter passes either a plain message or a platform event JSON payload and
receives one `chat_interaction/v1` envelope. The nested `chat_response/v1`
contains the user-facing headline, body, state, and platform-neutral actions
such as `accept_plan`, `revise_plan`, `send_to_codex`, `show_status`, or
`cancel`. Action labels do not expose `omh`, argv arrays, or shell command text.

`omh chat interact` composes existing deterministic primitives instead of
replacing them. Route-shaped turns use `omh chat route` semantics. Planning
turns use `hermes_plan/v1` and the existing `wrapper_contract` bridge.
Implementation-shaped turns can prepare a `coding_delegation/v1` payload and a
Codex-only `coding_executor_handoff/v1` when the route is safe to delegate.
Status turns wrap `delegated_coding_status/v1` into chat copy that separates
prepared, dispatched, executed, reviewed, verified, CI, and merged evidence.

The lower-level commands remain useful for debugging, tests, and custom
adapters:

- `omh chat route` returns only the deterministic route decision.
- `omh hermes plan` writes Hermes-facing plan Markdown under `.hermes/plans/`.
- `omh coding delegate` prepares a coding handoff without tracking lifecycle.
- `omh coding lifecycle` records and reports the Codex handoff lifecycle.

Actual Discord and Slack transports stay outside this repository. `omh` does
not open network connections, authenticate bots, post messages, invoke Codex, or
patch Hermes internals.

## Commands

| Command | Purpose |
| --- | --- |
| `omh install` | Install the built-in Hermes skill pack. |
| `omh update` | Reinstall from the built-in pack or a provided skill directory. |
| `omh convert --from-skills-dir <dir>` | Import local `SKILL.md` files into the managed pack. |
| `omh apply` | Register `~/.omh/skills` in Hermes `skills.external_dirs`. |
| `omh list` | Print the installed manifest. |
| `omh doctor` | Verify managed files and Hermes config registration. |
| `omh recommend <task>` | Deterministically suggest workflow skills from the local OMHM catalog. |
| `omh chat interact <message>` | Compose a wrapper-native `chat_interaction/v1` response for Discord, Slack, or hosted Hermes adapters. |
| `omh chat route <message>` | Route a plain chat message before a Discord, Slack, or Hermes wrapper dispatches it. |
| `omh coding delegate <task>` | Prepare a deterministic coding handoff payload and optional metadata-only runtime record. |
| `omh coding lifecycle <step>` | Start, dispatch, observe, verify, and report a Codex handoff lifecycle using local runtime evidence. |
| `omh hermes plan <task>` | Prepare a deterministic Hermes-facing plan, wrapper handoff contract, and optional `.hermes/plans` artifact. |
| `omh runtime status` | Inspect local runtime artifact state. |
| `omh runtime delegation-status --run <run-id>` | Summarize prepared/observed delegated coding status without overclaiming execution. |
| `omh runtime record` | Create a metadata-only workflow run artifact. |
| `omh runtime delegate` | Record observed or unavailable delegation for a run. |
| `omh runtime wrapper` | Record what a bot or wrapper actually observed for a run. |
| `omh runtime validate` | Validate runtime run, event, delegation, and wrapper artifacts. |
| `omh runtime export` | Export runtime evidence, redacted by default. |
| `omh state status` | Inspect file-backed workflow lifecycle state under `~/.omh/state`. |
| `omh docs workflows` | Print or verify the generated workflow reference from catalog data. |
| `omh probe` | Inspect observable Hermes capability surfaces without mutating internals. |
| `omh snippet` | Print optional workspace guidance without applying it. |
| `omh uninstall` | Remove Hermes config registration, optionally removing files. |

## Package Layout

```text
src/
  chat_router.py          deterministic chat pre-dispatch routing
  cli.py                 command-line entrypoint
  coding_lifecycle.py    wrapper-level Codex handoff lifecycle helpers
  coding_delegation.py   deterministic coding handoff preparation
  config_adapter.py      Hermes config registration adapter
  converter.py           local skill import support
  doctor.py              installation health checks
  hermes_planning.py     deterministic Hermes-facing plan artifacts
  installer.py           managed skill pack install/update/uninstall
  manifest.py            installed file manifest and conflict checks
  paths.py               home/config path resolution
  recommend.py           deterministic workflow skill recommender
  runtime_artifacts.py   runtime evidence read/write and validation helpers
  runtime_records.py     runtime schema builders and validators
  snippet.py             optional workspace guidance
  skill_pack.py          compatibility facade for generated skills
  wrapper_contract.py    platform-neutral chat interaction contracts
  core/
    errors.py            shared user-facing error type
  skills/
    catalog.py           workflow definitions and routing triggers
    render.py            generated Hermes skill content
```

The important design choice is that routing data lives in
`src/skills/catalog.py` and rendered skill text lives in
`src/skills/render.py`. This keeps the workflow registry testable as data
instead of burying routing behavior in one long string.

## Safety

- Existing managed files are protected by `~/.omh/manifest.json`.
- Local modifications are not overwritten unless `--force` is supplied.
- `omh apply --dry-run` shows config changes without writing.
- `omh uninstall` removes config registration first; file deletion requires
  `--remove-files`.
- Tests use temporary homes and do not mutate the real `~/.hermes`.

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

- Versioned release artifacts for stable installer targets
- A richer generated routing registry
- More artifact-backed bot and workflow examples
- More Hermes-specific diagnostics in `omh doctor`
- Command-level tests for uninstall, snippet output, and imported skill edge cases
- Workflow fixtures that verify generated skill behavior remains conservative
