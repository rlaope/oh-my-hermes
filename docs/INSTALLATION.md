# Installation

This guide is for users who want to install and apply the Hermes skill pack
without cloning this repository.

## Install

Run the installer:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
```

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
```

`omh doctor` should report a healthy installation. `omh list` should show the
managed skills available to Hermes. `omh runtime status` should show the local
runtime artifact directory and the latest install/apply/doctor state when those
commands have run.

For concrete examples that show how the installed skills should affect coding,
planning, and specialist review flows, see
[Application Cases](APPLICATION_CASES.md).

## Discord Bot Flow

If Hermes Agent is running behind a Discord bot, install `oh-my-hermes-agent` on
the same machine, container, or runtime image that starts the bot.

The flow is:

1. The Discord bot receives a user message.
2. The bot forwards that request to Hermes Agent.
3. Hermes starts with its normal config and reads `skills.external_dirs`.
4. `omh apply` makes sure `~/.omh/skills` is included in that discovery list.
5. Hermes sees the managed skills, including the `oh-my-hermes` router skill.
6. The router skill gives Hermes prompt-level routing guidance for workflow
   names, trigger phrases, fallback rules, and recovery behavior.
7. Hermes selects the relevant installed skill and continues the response inside
   the Discord bot flow.
8. The bot or operator can record local evidence with `omh runtime record` and
   `omh runtime delegate`.

`omh` does not replace the Discord bot, modify Discord commands, or patch Hermes
internals. It prepares the skill layer that Hermes can load when the bot invokes
Hermes.

For a hosted bot, the practical deployment shape is usually:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh doctor
```

Then restart the bot process so Hermes reloads its config and skill directory.

Optional artifact-backed flow:

```sh
run_json="$(omh runtime record --skill oh-my-hermes --harness coding-handling --status started)"
run_id="$(printf '%s' "$run_json" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"

# After Hermes responds, record what the bot could actually observe.
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed
omh runtime wrapper --run "$run_id" --prompt-dispatched --response-observed --completion-status completed --gap "specialist lane metadata not exposed"
omh runtime validate --run "$run_id"
omh runtime show "$run_id"
```

For hosted bots, run these commands inside the same container, virtual
environment, or user account that owns the bot runtime. If the wrapper can
observe a specialist lane result, record it with `--observed`; otherwise keep
the result as `not_observed`.

Use `omh runtime export --redacted` when you need a portable support artifact.
Exports redact prompt, response, token, secret, key, and password-shaped fields by
default while preserving proof fields such as run status, event names, observed
delegation flags, and wrapper completion status.

## Review Checklist

Before calling the bot integration ready, verify these points:

- The installer ran in the same runtime context as the Discord bot.
- `omh doctor` reports the managed skill directory as installed and registered.
- The bot process can read the same Hermes home/config that `omh apply` updated.
- The bot was restarted after installation or update.
- A Discord message that strongly names a workflow reaches Hermes with installed
  skill descriptions available.
- `omh runtime record` can create a run and `omh runtime show <run-id>` can read
  it from the same runtime context.
- If skills do not appear, run `omh apply`, then `omh doctor`, then restart the
  bot again.

Current limitation: routing is prompt-level guidance. It depends on Hermes
loading and exposing installed skills to the model. If the Discord bot runs
Hermes in a restricted mode that does not load external skill directories, the
bot adapter or Hermes startup config must be updated to allow that discovery
path.

## Update

Update the installed skill pack:

```sh
omh update
omh apply
omh doctor
```

Use `omh apply` after an update to make sure Hermes still has the managed skill
directory registered.

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
