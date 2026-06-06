# Installation

This guide is for users who want to install and apply the Hermes skill pack
without cloning this repository.

## Install

Run the installer:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
```

By default this installs the preview channel from the `main` branch archive.
For pinned stable installs, pass a release version after the matching
`v<version>` tag exists:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

For custom release archives or local package sources accepted by `pip`, pass
`OMH_PACKAGE_URL`.

The installer prepares the `omh` command, installs the managed Hermes skills,
registers the managed skill directory with Hermes, and checks the result.

After it finishes, restart Hermes Agent so it can reload the registered skill
directory.

## Verify

Check the installation:

```sh
omh doctor
omh list
omh runtime status
omh probe
```

`omh doctor` should report a healthy installation. `omh list` should show the
managed skills available to Hermes. `omh runtime status` should show the local
runtime artifact directory and the latest install/apply/doctor state when those
commands have run. `omh probe` reports observable Hermes capability surfaces
without mutating Hermes internals.

For concrete examples that show how the installed skills should affect coding,
planning, and specialist review flows, see
[Application Cases](APPLICATION_CASES.md).

The public project site at
`https://rlaope.github.io/oh-my-hermes-agent/` is a short entry point. Treat
this `docs/` directory and the root README as the source of truth for operating
details.

## Chat Wrapper Flow

If Hermes Agent is running behind a Discord bot, Slack app, or hosted chat
adapter, install `oh-my-hermes-agent` on the same machine, container, or runtime
image that starts the wrapper.

The flow is:

1. The wrapper receives a user message in Discord, Slack, or another chat
   surface.
2. The wrapper calls `omh chat interact` with the platform source and either a
   plain message or event JSON.
3. `omh` returns one `chat_interaction/v1` envelope with a renderable
   `chat_response/v1`, optional `status_card/v1`, a stable `thread_key`,
   platform-neutral actions, and a conservative `next_action`.
4. The wrapper renders `chat_response.headline`, `body`, `state`, `actions`, and
   `status_card` when present in the original channel or thread. The user does
   not need to know any `omh` command names.
5. If the interaction asks for clarification, the wrapper keeps the answer in
   the same thread and calls `omh chat interact` again with the updated message.
6. If the interaction presents a plan, the wrapper waits for the user to accept
   or revise it before preparing any coding handoff.
7. If the accepted interaction exposes `send_to_codex`, the wrapper starts a
   Codex lifecycle run, dispatches the handoff to the external Codex-like
   executor, and records only what it actually observes.
8. Status updates use `omh coding lifecycle report` or
   `omh chat interact --run <run-id>` and stay in the same thread.
9. Hermes still starts with its normal config and reads `skills.external_dirs`;
   `omh apply` makes sure `~/.omh/skills` is included in that discovery list.

`omh` does not replace the Discord bot, modify Slack commands, open network
connections, invoke Codex, or patch Hermes internals. It prepares deterministic
local contracts that a wrapper can render, dispatch, and later update with
observed evidence.

For a hosted bot, the practical deployment shape is usually:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh doctor
```

Then restart the bot process so Hermes reloads its config and skill directory.

Minimal wrapper calls:

```sh
omh chat interact --source discord --event-json event.json
omh chat interact --source slack "risky refactor"
printf '%s' "$SLACK_TEXT" | omh chat interact --source slack --stdin
```

Codex lifecycle calls after the wrapper has an accepted coding handoff:

```sh
start_json="$(omh coding lifecycle start --executor codex --record "risky refactor")"
run_id="$(printf '%s' "$start_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"

# Dispatch to the external Codex-like executor outside OMHM, then record the
# wrapper-observed transition.
omh coding lifecycle dispatch --run "$run_id"
omh coding lifecycle result --run "$run_id" --result completed --evidence-ref codex-log
omh coding lifecycle verify --run "$run_id" --completion-status completed
omh runtime review --run "$run_id" --status passed --reviewer code-review --evidence-ref review-comment
omh runtime ci --run "$run_id" --status passed --check "unit:passed"
omh runtime merge --run "$run_id" --ready --target-branch main
omh coding lifecycle report --run "$run_id"
```

The lifecycle commands write the same local runtime artifacts as the lower-level
runtime commands. They reject invalid transitions, keep prepared handoff separate
from execution evidence, and continue to block final completion copy when review
verification, review, CI, or merge-readiness evidence is missing.

Lower-level debug surfaces remain available when an adapter needs them:

```sh
omh chat route --source discord --record "risky refactor"
omh hermes plan --source discord --record "risky refactor with review"
omh coding delegate --executor codex --source discord --record "risky refactor"
omh runtime delegation-status --run <run-id>
```

`omh hermes plan --record` writes a draft `hermes_plan/v1` Markdown artifact
under `.hermes/plans/`. Each plan includes a deterministic `quality_gate` and
`deep_interview` block. Weak planning requests may also write `.hermes/context/`
so Hermes can ask one blocking clarification. Review gates remain
`not_observed` unless the wrapper can prove a separate review happened.

The stdout JSON also includes `wrapper_contract`. Wrappers should use that JSON,
not the Markdown body, to decide the next local action. If
`wrapper_contract.coding_delegate.available` is `true`, the listed
`argv_template` is an adapter contract for preparing a lower-level delegation
after plan acceptance. If it is `false`, follow `next_action` and do not dispatch
coding work.

For hosted bots, run these commands inside the same container, virtual
environment, or user account that owns the wrapper runtime. If the wrapper can
observe executor, review, verification, CI, or merge evidence, record it
explicitly; otherwise keep the status conservative.

Wrapper-facing golden examples live under `examples/wrapper-golden/`. They show
the expected `chat_response/v1` copy, `deep_interview_contract/v1`, optional
`status_card/v1`, and platform-neutral action ids for clarification, planning,
handoff, review, CI, merge-ready, merged, and contradictory-evidence states.
`examples/wrapper-golden/harness-quality.json` shows how wrappers can map
`harness_quality/v1` into visible buttons, progress steps, and overclaim guards.

To inspect the live catalog contract that generated skills and wrappers share:

```sh
omh docs workflows --json
omh harness list
omh harness inspect planning
omh harness validate
```

Use `omh runtime export --redacted` when you need a portable support artifact.
Exports redact prompt, response, token, secret, key, and password-shaped fields by
default while preserving proof fields such as run status, event names, observed
delegation flags, and wrapper completion status.

## Review Checklist

Before calling the bot integration ready, verify these points:

- The installer ran in the same runtime context as the Discord, Slack, or hosted
  chat wrapper.
- `omh doctor` reports the managed skill directory as installed and registered.
- The bot process can read the same Hermes home/config that `omh apply` updated.
- The bot was restarted after installation or update.
- `omh chat interact --source discord "<message>"` or
  `omh chat interact --source slack "<message>"` returns a
  `chat_interaction/v1` envelope with a renderable `chat_response/v1`.
- The rendered `chat_response` does not expose `omh`, argv arrays, or shell
  command text to the end user.
- Clarification and fallback interactions do not expose `send_to_codex`.
- `omh chat route --source discord --record "<message>"` returns a route action
  and writes `routing.json` in the same runtime context as the wrapper when the
  lower-level route command is used.
- `omh coding delegate --source discord --record "<message>"` returns a
  `coding_delegation/v1` payload and writes `coding_delegation.json` with
  status `prepared_not_observed` for implementation-shaped requests when the
  lower-level delegate command is used.
- `omh coding lifecycle start --executor codex --record "<message>"` creates a
  prepared Codex handoff lifecycle without storing the raw prompt body by
  default.
- `omh coding lifecycle result --run <run-id> --result completed` is rejected
  until `omh coding lifecycle dispatch --run <run-id>` records dispatch
  observation.
- `omh coding lifecycle report --run <run-id>` does not claim final completion
  while executor, verification, review, CI, or merge-readiness evidence is
  missing.
- `omh hermes plan --source discord --record "<message>"` writes a
  `hermes_plan/v1` artifact under the same Hermes home that the bot uses.
- That planning command does not create a runtime `run.json` or
  `coding_delegation.json`; `.hermes/plans/` is a user-facing draft surface, not
  observed execution evidence.
- If a wrapper needs machine-readable planning fields, use the stdout
  `hermes_plan/v1` JSON payload as the contract and treat the Markdown file as
  presentation.
- For implementation-shaped draft plans, the stdout
  `wrapper_contract.coding_delegate.argv_template` is the handoff bridge to
  `omh coding delegate --record`; run it only after plan acceptance and with the
  original message preserved.
- A chat message that strongly names a workflow reaches Hermes with installed
  skill descriptions available after the wrapper dispatches to Hermes.
- `omh runtime record` can create a run and `omh runtime show <run-id>` can read
  it from the same runtime context.
- `omh probe` reports managed skills and external skill directory registration
  as available before any deeper integration claim is made.
- If skills do not appear, run `omh apply`, then `omh doctor`, then restart the
  bot again.

Current limitation: actual Discord, Slack, Hermes, Codex, GitHub, CI, and merge
operations still happen outside OMHM. `omh chat interact`, `omh chat route`,
`omh coding delegate`, and `omh coding lifecycle` choose contracts and record
local metadata, but the wrapper adapter must render messages, dispatch to Hermes
or Codex-like executors, and record only evidence it actually observed.

## Update

Update the installed skill pack:

```sh
omh update --channel preview
omh apply
omh doctor
```

Use `omh update --channel stable --version <version>` to record a pinned stable
update intent, or `omh update --channel local --from-skills-dir ./skills` for a
local fixture. Local modifications block updates unless `--force` is supplied.
Use `omh apply` after an update to make sure Hermes still has the managed skill
directory registered, then restart Hermes Agent.

## Reapply

If Hermes does not show the installed skills, reapply the config registration:

```sh
omh apply
omh doctor
```

Then restart Hermes Agent.

## Install Options

Skip automatic Hermes config registration:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_AUTO_APPLY=0 sh
```

Skip the final health check:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_RUN_DOCTOR=0 sh
```

Use the active environment instead of a user-level install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_PIP_ARGS= sh
```

## Uninstall

Remove the Hermes config registration:

```sh
omh uninstall
```

Remove the registration and managed files:

```sh
omh uninstall --remove-files
```
