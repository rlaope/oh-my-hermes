# Installation

This guide is for users and operators who want Hermes Agent to see the OMH
skill pack. Normal users should talk to Hermes through Hermes' skill and chat
surfaces. The `omh` command is bootstrap, repair, verification, and wrapper
backend infrastructure.

AI agents and operators who need a pasteable protocol should use the root
[Agent Install Protocol](../INSTALL_FOR_AGENTS.md). That protocol defines what
to run, what to report, and what is still unobserved after install.

## Quick Start

Use this when you just want Hermes to see OMH skills and have the local
maintenance command available:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
omh doctor
```

The installer normally runs setup automatically, but `omh setup` is kept here
as the explicit repairable step: it installs generated managed skills and
registers them with Hermes through `skills.external_dirs`.
When `omh setup` is run in a real terminal, it opens a small colored wizard that
detects the Hermes config path, confirms skill registration, asks for the
default coding executor preference, and can opt into the plugin bridge or a
visible team persona. In non-interactive shells it uses safe defaults and prints
a concise step-by-step summary. Use
`omh setup --json` or `OMH_OUTPUT=json omh setup` for the full
machine-readable payload.

The installer also prints the installed `omh` command path. By default it uses
an isolated OMH virtual environment and links `omh` into a user bin directory
when possible. If that directory is not on `PATH`, add the printed directory to
`PATH` or run the printed absolute `omh` path directly.

Plugin support is optional. Use it when an operator wants OMH to provide a
thin Hermes plugin bridge in addition to the skill pack:

```sh
omh setup --with-plugin
omh doctor
```

That installs `~/.hermes/plugins/omh` with metadata-only status support. It
does not execute code, install Discord or Slack transports, patch Hermes core,
or prove Hermes has loaded the plugin. If the target Hermes runtime requires a
separate plugin enable command, follow that runtime's plugin enable/reload step.

## Install Path A: Hermes-Native Skill Tap

Use this path when the target Hermes environment supports skill taps:

```sh
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes
```

Use the full identifier for first install. It avoids short-name resolver
ambiguity in current Hermes CLI releases while installing the same
`oh-my-hermes` skill.

Install additional workflow skills when you want direct Hermes skill surfaces:

```sh
hermes skills install deep-interview
hermes skills install ralplan
hermes skills install web-research
hermes skills install code-review
```

This path reads the tap-compatible skill pack under `skills/` in this
repository. After installation, restart or refresh Hermes Agent if the target
environment requires it, then use Hermes normally:

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

Hermes should route through the installed skill guidance, name the responsible
role, and show the next action without asking the chat user to run `omh`
commands.

## Hermes CLI Release Smoke

For release candidates, OMH provides a dedicated smoke contract for the real
Hermes CLI install path. The default command is a plan-only check that can run
in CI without touching the current Hermes profile:

```sh
omh release hermes-smoke
```

When an operator explicitly wants live evidence from the target Hermes profile,
run one of these:

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup
```

The live smoke runs the selected install path and then verifies:

```sh
hermes skills tap list
hermes skills list --enabled-only
hermes skills check oh-my-hermes
hermes skills inspect rlaope/oh-my-hermes-agent/skills/oh-my-hermes
```

The tap path proves Hermes CLI install/list/check/inspect for the target
profile. The setup path proves `skills.external_dirs` discovery with
list/check plus `omh doctor`, because current Hermes CLI releases do not
reliably inspect local external-dir skills by short name. Neither path proves
that a later Hermes chat session selected OMH unless that chat response is
observed separately.

## Install Path B: OMH Bootstrap Setup

Use this path when you want a Python installer, generated managed skills,
local doctor checks, or wrapper/backend operations in the same runtime context
as a hosted Hermes wrapper.

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

The installer creates an isolated OMH virtual environment, links the `omh`
command into `~/.local/bin` when possible, runs `omh setup` to install managed
Hermes skills and register the managed skill directory with Hermes, then runs
`omh doctor` as a separate health check. This avoids Homebrew and distro Python
`externally-managed-environment` failures while keeping the user-facing command
simple.

Installer and setup output can be localized with `OMH_LANG` or `--language`.
Supported language codes are `en`, `ko`, `ja`, and `zh`:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_LANG=ko sh
omh setup --language ko
```

From the user's point of view, the intended final state matches the Hermes tap
path: Hermes can discover OMH skills and the user talks to Hermes. `omh setup`
is the bootstrap/maintenance route that produces that state through generated
skills and `skills.external_dirs`.

After it finishes, restart Hermes Agent or the hosted wrapper so it can reload
the registered skill directory.

## Set Up And Verify

The installer runs setup automatically. Re-run it when you want to repair or
refresh the local Hermes skill registration:

```sh
omh setup
omh doctor
omh list
omh runtime status
omh probe
```

`omh setup` should report a human-readable setup summary by default. In a real
terminal it first asks for setup language, then only asks for choices that
change behavior. The same command with `--json` should include install and apply
steps plus a
`hermes_native_setup/v1` block that names the equivalent Hermes skill install
path, managed skill directory, and `skills.external_dirs` registration key.
`hermes_native.observed` means the local bootstrap/apply step actually ran; it
does not prove Hermes has reloaded or used the skill yet.
`discovery_status: config_registered_reload_required` means restart or refresh
Hermes before claiming the skill is visible in chat.
`omh doctor` should report a healthy summary by default; `omh doctor --json`
returns the full check payload. `omh list` should show the managed skills
available to Hermes.
`omh install` and `omh update` also print concise summaries by default; use
`--json` or `OMH_OUTPUT=json` when a wrapper or automation needs the complete
manifest payload.
`omh runtime status` should show the local runtime artifact directory and the
latest install/apply/doctor state when those commands have run. `omh probe`
reports observable Hermes capability surfaces without mutating Hermes internals.
When `omh setup --with-plugin` has run, `omh doctor` also checks the managed
plugin manifest plus local import/register smoke. `omh probe` reports
`plugin_distribution_ready` separately from `native_integration_claim_ready` so
operators do not mistake local install readiness for observed Hermes runtime
use.

For concrete examples that show how the installed skills should affect coding,
planning, and specialist review flows, see
[Application Cases](APPLICATION_CASES.md).

The public project site at
`https://rlaope.github.io/oh-my-hermes-agent/` is a short entry point. Treat
this `docs/` directory and the root README as the source of truth for operating
details.

## Chat Wrapper Backend Flow

If Hermes Agent is running behind a Discord bot, Slack app, or hosted chat
adapter, install `oh-my-hermes-agent` on the same machine, container, or runtime
image that starts the wrapper.

The backend flow is:

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
7. If the accepted interaction exposes executor selection or a handoff action,
   the wrapper uses the chosen executor profile. Codex can use the run-backed
   lifecycle path; Claude Code, OMH-style runtime profiles, generic agents, and
   Hermes-retained work use prompt-only or retained handoff paths in Phase 1.
   The wrapper records only what it actually observes.
8. If the wrapper observes Hermes target metadata such as `agent_ref`,
   `agent_count`, or `hermes_home`, `chat_interaction/v1` may include
   `target_notice` and `target_topology`. Render the concise notice or
   `apply_target_change` action before treating single-to-multi or
   multi-to-single target changes as persistent setup state. When target
   identity metadata is present, `thread_key` is scoped by that target so two
   Hermes agents in the same channel do not share wrapper session state.
9. If the wrapper has local memory-like context candidates, it can run
   `omh memory inspect` and attach a conflict-free `handoff_context_pack/v1` to
   the later handoff. Conflicting or stale assumptions must be shown as memory
   review, not silently reused.
10. Status updates use `omh coding lifecycle report` or
   `omh chat interact --run <run-id>` and stay in the same thread.
11. Hermes still starts with its normal config and reads `skills.external_dirs`;
   `omh apply` makes sure `~/.omh/skills` is included in that discovery list.

`omh` does not replace the Discord bot, modify Slack commands, open network
connections, invoke coding executors, or patch Hermes internals. It prepares
deterministic local contracts that a wrapper can render, dispatch, and later
update with observed evidence.

For a hosted bot, the practical bootstrap shape is usually:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
omh doctor
```

Then restart the bot process so Hermes reloads its config and skill directory.

Minimal wrapper calls:

```sh
omh chat interact --source discord --event-json event.json
omh chat interact --source slack "risky refactor"
printf '%s' "$SLACK_TEXT" | omh chat interact --source slack --stdin
```

If the wrapper can identify the current Hermes agent target, include that as
metadata rather than asking the user to choose a command:

```json
{
  "message": {"id": "m1", "content": "risky refactor", "channel": "dev"},
  "agent": {"id": "hermes-dev-1"},
  "runtime": {"hermes_home": "/srv/hermes/dev", "agent_count": 2}
}
```

With `--auto-apply-target-change`, OMH persists the observed target registry
update and registers the managed skill directory for the reported
`hermes_home`. Without that flag, the wrapper gets a pending
`apply_target_change` action and should ask the user before persisting the
single-to-multi or multi-to-single setup change. The action payload includes
`target_observation.source_metadata`, which is the sanitized metadata needed to
apply that exact target update without storing or replaying the raw chat prompt.

Choose an executor profile for an accepted coding handoff:

```sh
omh chat session select-executor "$session_id" codex
omh chat session select-executor "$session_id" claude-code
omh chat session select-executor "$session_id" generic
```

Review stale local context before a handoff:

```sh
omh memory inspect --fixture wrapper-memory.json
omh memory pack --fixture wrapper-memory.json --executor codex --session-id "$session_id" > handoff-context.json
omh chat session prepare-handoff "$session_id" --context-pack handoff-context.json "risky refactor"
```

`memory_review_card/v1` is separate from `status_card/v1`. It can drive
`keep_memory`, `forget_memory`, `update_memory`, `change_memory_scope`,
`apply_memory_updates`, and `show_memory_status` buttons. Approved changes are
written only to `.omh/memory/`; OMH does not read or mutate opaque Hermes
internal memory.

Codex lifecycle calls after the wrapper has an accepted Codex coding handoff:

```sh
start_json="$(omh coding lifecycle start --executor codex --record "risky refactor")"
run_id="$(printf '%s' "$start_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"

# Dispatch to the external Codex executor outside OMH, then record the
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
omh coding delegate --executor claude-code --source discord --record "risky refactor"
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

## What Gets Recorded

`omh` records runtime metadata only by default:

- setup/install/apply/doctor summaries in `~/.omh/runtime/state.json`
- workflow run envelopes in `~/.omh/runtime/runs/<run-id>/run.json`
- append-only run events in `events.jsonl`
- wrapper chat sessions in `~/.omh/runtime/wrapper_sessions/<session-id>/`
- delegation observation in `delegation.json`
- prepared coding handoffs in `coding_delegation.json`
- wrapper observation in `wrapper.json`
- review, CI, and merge evidence in `review.json`, `ci.json`, and `merge.json`

Prepared handoff is never treated as implementation, review, CI, or merge
evidence by itself. If the wrapper cannot prove that a step happened, status
should stay `prepared_not_observed`, `not_observed`, or `not_available`.

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
- Clarification and fallback interactions do not expose `send_to_executor` or
  `send_to_codex`.
- `omh chat route --source discord --record "<message>"` returns a route action
  and writes `routing.json` in the same runtime context as the wrapper when the
  lower-level route command is used.
- `omh coding delegate --executor codex --source discord --record "<message>"`
  returns a `coding_delegation/v1` payload and writes `coding_delegation.json`
  with status `prepared_not_observed` when the payload contains a real Codex
  `executor_handoff`.
- `omh coding lifecycle start --executor codex --record "<message>"` creates a
  prepared Codex handoff lifecycle without storing the raw prompt body by
  default.
- `omh coding delegate --executor claude-code --record "<message>"` and other
  non-Codex profiles return a `coding_prompt_handoff/v1` prompt-only payload
  without creating a lifecycle run.
- Executor-choice, retained-Hermes, clarify, fallback, and prompt-only handoffs
  return `runtime.recorded=false`; wrappers should not expect
  `runtime.run.run_id` for those paths.
- Codex handoff payloads expose `codex_skill` plus
  `codex_invocation.dispatch_text_template`, for example
  `$ai-slop-cleaner {message}`. The wrapper replaces `{message}` only when it
  dispatches to Codex.
- `omh memory pack` attaches `context_pack` only when no unresolved memory
  conflict remains; otherwise the handoff contains `context_pack_blocked`.
- `omh memory apply --batch <file> --dry-run` previews approved memory updates
  without writing, and the real apply writes only under `.omh/memory/`.
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
  `omh coding delegate --executor codex --record`; run it only after plan
  acceptance and with the original message preserved when the wrapper wants a
  run-backed Codex handoff.
- A chat message that strongly names a workflow reaches Hermes with installed
  skill descriptions available after the wrapper dispatches to Hermes.
- `omh runtime record` can create a run and `omh runtime show <run-id>` can read
  it from the same runtime context.
- `omh probe` reports managed skills and external skill directory registration
  as available before any deeper integration claim is made.
- If skills do not appear, run `omh setup`, then `omh doctor`, then restart the
  bot again.

Current limitation: actual Discord, Slack, Hermes, coding executors, GitHub, CI,
and merge operations still happen outside OMH. `omh chat interact`,
`omh chat route`, `omh coding delegate`, and `omh coding lifecycle` choose
contracts and record local metadata, but the wrapper adapter must render
messages, dispatch to Hermes or the selected coding executor, and record only
evidence it actually observed.

## Update

Update the installed skill pack:

```sh
omh update --channel preview
omh setup
omh doctor
```

Use `omh update --channel stable --version <version>` to record a pinned stable
update intent, or `omh update --channel local --from-skills-dir ./skills` for a
local fixture. Local modifications block updates unless `--force` is supplied.
Use `omh setup` after an update to reinstall managed skills and reapply Hermes
registration. Then run `omh doctor` and restart Hermes Agent.

## Reapply

If Hermes does not show the installed skills, reapply the config registration:

```sh
omh setup
omh doctor
```

Then restart Hermes Agent.

## Install Options

Install the optional plugin bridge during bootstrap:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_WITH_PLUGIN=1 sh
```

Install one or more optional Hermes agent/profile packs during bootstrap. These
are visible role/persona files only; all OMH workflows are installed either way:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_PROFILE_PACKS=cto-loop,startup-delivery sh
```

Record a default executor preference during bootstrap:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_DEFAULT_EXECUTOR=claude-code sh
```

Supported values are `choose`, `hermes`, `codex`, `claude-code`, `generic`,
`omx-runtime`, `omo-runtime`, and `omc-runtime`. The recommended default is
`choose`, which asks before dispatch. Legacy `OMH_SETUP_PROFILES=1,3` still maps
to setup profile categories for automation that already uses it, but new scripts
should prefer `OMH_DEFAULT_EXECUTOR`.

Choose installer/setup output language during bootstrap:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_LANG=ja sh
```

Supported values are `en`, `ko`, `ja`, and `zh`. The same setting can be passed
directly to setup with `omh setup --language zh`.

Skip automatic Hermes config registration:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_AUTO_APPLY=0 sh
```

Skip the final health check:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_RUN_DOCTOR=0 sh
```

Use the active Python environment instead of the default isolated venv:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_INSTALL_MODE=python OMH_PIP_ARGS= sh
```

Customize the isolated install locations:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_VENV_DIR="$HOME/.local/share/omh/venv" OMH_BIN_DIR="$HOME/.local/bin" sh
```

Pass a current `omh setup` flag before `install.sh` has a first-class
environment variable for it:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_SETUP_ARGS="--dry-run" sh
```

`OMH_SETUP_ARGS` is an advanced escape hatch. Prefer the named variables above
for stable install recipes.

## Uninstall

Remove OMH-managed local state and Hermes integration files:

```sh
omh uninstall
```

This unregisters `~/.omh/skills` from Hermes config, removes `~/.omh`, removes
the managed `~/.hermes/plugins/omh` plugin bundle when it has an OMH manifest,
removes generated team role files recorded in OMH team-profile manifests, and
removes the install.sh-managed `omh` command venv/link when the current command
is running from that managed venv. It does not delete unrelated Hermes files,
unrelated plugins, unrelated agents, or pipx/development Python environments
that OMH cannot safely identify as install.sh-managed.

Preview the cleanup first:

```sh
omh uninstall --dry-run
```

Only remove the Hermes config registration:

```sh
omh uninstall --registration-only
```

Legacy cleanup for just the registration plus managed `~/.omh` directory:

```sh
omh uninstall --remove-files
```

`omh uninstall --all` and `omh uninstall --purge` are explicit aliases for the
default full cleanup. Add `--force` only when you intentionally want to remove
an unmanaged `~/.hermes/plugins/omh` directory. Add `--keep-command` when you
want to keep the install.sh-managed command venv/link while removing Hermes
state.
