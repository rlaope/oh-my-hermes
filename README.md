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
application cases, runtime diagnostics, local runtime artifacts, CI, and
contributor guidance. The next direction is deeper Hermes-side integration:
richer routing metadata, stronger wrapper examples, release packaging, and
Hermes-specific workflow tests.

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

Useful commands:

```sh
omh install --dry-run
omh install --from-skills-dir ./skills
omh update --from-skills-dir ./skills
omh apply --dry-run
omh recommend "risky refactor"
omh chat route --source discord --record "risky refactor"
omh coding delegate --source discord --record "risky refactor"
omh hermes plan --record "risky refactor with review"
omh runtime record --skill oh-my-hermes --harness coding-handling --status started
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

`omh` adds five things around it:

1. A managed skill directory at `~/.omh/skills`
2. A manifest at `~/.omh/manifest.json`
3. Local runtime artifacts under `~/.omh/runtime`
4. A config registration in Hermes' `skills.external_dirs`
5. Hermes-facing planning artifacts under `~/.hermes/plans`

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

Coding delegation artifacts separate a prepared executor handoff from observed
execution. `omh coding delegate --record` stores the recommended workflow,
harness, acceptance criteria, verification expectations, source references,
recommendation evidence, `message_sha256`, `message_length`, and status
`prepared_not_observed`; it does not store the raw prompt body by default. Its
companion `run.json` is bookkeeping for that prepared handoff and is marked
`status: prepared`,
`artifact_kind: prepared_coding_delegation`, `phase: prepared`, and
`observation_status: prepared_not_observed`.

Delegation artifacts separate `requested` from `observed`. If Hermes or a bot
wrapper cannot prove that a specialist lane actually ran, the result should stay
`not_observed` or `not_available`.

Bot wrappers can also record what they actually observed:

```sh
omh runtime wrapper --run <run-id> --prompt-dispatched --response-observed --completion-status completed
omh runtime validate --run <run-id>
omh runtime export --redacted
```

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

Wrappers for Discord, Slack, or hosted Hermes chats can run `omh chat route`
before forwarding a plain user message. The command returns a deterministic
`dispatch`, `clarify`, or `fallback` decision plus a `routing_instruction` and
`routing_prompt_template`. The default JSON omits the raw prompt body so wrapper
logs can stay metadata-only; use `--include-message` only when the wrapper needs
`route.routing_prompt` pre-expanded. With `--record`, it writes metadata-only
`routing.json` evidence under `.omh/runtime/` without storing the raw prompt.

For implementation-shaped chat messages, wrappers can run `omh coding delegate`
to prepare a deterministic executor handoff from the same local catalog
metadata. It returns a `coding_delegation/v1` payload with action, intent,
recommended workflow, harness, acceptance criteria, verification expectations,
and a `delegation_prompt_template`. With `--record`, it writes
`coding_delegation.json` evidence and a `prepared_coding_delegation` run
envelope; validation treats those as a required pair. The wrapper still needs
separate Hermes or bot evidence before claiming execution was observed.

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to
create a deterministic `hermes_plan/v1` scaffold. With `--record`, it writes a
Markdown plan under `.hermes/plans/` with goals, non-goals, options, risks,
acceptance criteria, verification, execution handoff guidance, and a review
gate. The review gate is `not_observed` by default; the plan is a draft until a
wrapper or human review supplies evidence. Weak requests also write a
`.hermes/context/` artifact so Hermes can ask one blocking clarification before
planning.

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
| `omh chat route <message>` | Route a plain chat message before a Discord, Slack, or Hermes wrapper dispatches it. |
| `omh coding delegate <task>` | Prepare a deterministic coding handoff payload and optional metadata-only runtime record. |
| `omh hermes plan <task>` | Prepare a deterministic Hermes-facing plan and optionally write it under `.hermes/plans`. |
| `omh runtime status` | Inspect local runtime artifact state. |
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
  coding_delegation.py   deterministic coding handoff preparation
  config_adapter.py      Hermes config registration adapter
  converter.py           local skill import support
  doctor.py              installation health checks
  installer.py           managed skill pack install/update/uninstall
  manifest.py            installed file manifest and conflict checks
  paths.py               home/config path resolution
  recommend.py           deterministic workflow skill recommender
  snippet.py             optional workspace guidance
  skill_pack.py          compatibility facade for generated skills
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
