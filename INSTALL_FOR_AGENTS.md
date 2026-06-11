# OMH Agent Install Protocol

Canonical install reference for AI agents and operators. Execute top to bottom,
then report the observed result. Normal users should use Hermes chat and
installed skills; `omh` is bootstrap, repair, doctor, and backend verifier
infrastructure.

## Prerequisites

```sh
command -v python3 >/dev/null || echo "MISSING: python3 is required"
command -v git >/dev/null || echo "MISSING: git is required for source installs"
command -v hermes >/dev/null || echo "NOTE: Hermes Agent command not found in PATH"
```

If Hermes is not available, continue only when the target environment uses a
hosted wrapper that manages Hermes separately. Do not claim Hermes-visible
readiness until the target Hermes runtime or wrapper has been checked.

## Step 1: Install OMH

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

The installer prepares the local `omh` command and normally runs setup. Re-run
setup explicitly because it is the repairable, repeatable step:

```sh
omh setup
```

Expected local result:

- generated skills are installed under `~/.omh/skills`;
- Hermes config includes that directory in `skills.external_dirs`;
- normal users can talk to Hermes instead of running backend commands.

## Step 2: Verify

```sh
omh doctor
```

Report:

- `ok`;
- top-level `recommended_next_action`;
- any check with `severity: blocking`;
- any check with `severity: warning`;
- whether the target Hermes runtime still needs restart/reload.

Install success means a Hermes-usable skill path is configured and doctor has no
blocking checks. It does not mean Hermes has already reloaded the skills,
loaded the optional plugin, executed code, reviewed a PR, passed CI, or merged.

For release-candidate verification, add the Hermes CLI smoke. Plan mode is safe
and non-mutating:

```sh
omh release hermes-smoke
```

When the operator explicitly wants to prove the current Hermes profile can
install, list, check, and inspect OMH, run one live smoke:

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
```

Use `--install-path setup` instead when the release must prove the `omh setup`
bootstrap path. Passing either live smoke still does not prove a later Hermes
chat session selected OMH unless that chat response is observed separately.

## Optional Hermes Skill Tap

If the target Hermes environment supports skill taps, this is the native front
door:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

Install direct workflow skills only when the user wants them exposed as explicit
Hermes skill choices:

```sh
hermes skills install deep-interview
hermes skills install ralplan
hermes skills install web-research
hermes skills install feedback-triage
hermes skills install ops-review
hermes skills install code-review
```

The tap path and `omh setup` path should converge on the same user experience:
Hermes can see OMH guidance and the user talks to Hermes.

## Optional Plugin Bridge

Use the plugin only when the operator wants the thin native bridge in addition
to skills:

```sh
omh setup --with-plugin
omh doctor
```

This installs `~/.hermes/plugins/omh` and lets doctor verify local manifest,
import, and register smoke checks. It does not patch Hermes core, implement
Discord or Slack transports, start a network service, or prove Hermes loaded
the plugin. Runtime plugin use must be observed separately.

The one-command installer can include the same optional bridge or profile packs
when the operator explicitly wants them:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_WITH_PLUGIN=1 OMH_PROFILE_PACKS=cto-loop sh
```

## First Hermes Prompt

After install and any required Hermes restart/reload, try:

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

Expected behavior:

- Hermes explains why `request-to-handoff` is the right first workflow;
- Hermes names the responsible role such as `planning-lead` or
  `coding-handoff`;
- Hermes gives the next action, such as clarify, accept plan, choose executor,
  or show status;
- Hermes keeps prepared handoff separate from observed execution evidence.

## Failure Report Template

```text
OMH install result:
- install command:
- omh setup output summary:
- omh doctor ok:
- recommended_next_action:
- blocking checks:
- warning checks:
- Hermes restart/reload performed:
- first Hermes prompt tried:
- observed Hermes response:
```

Do not ask the user for Discord, Slack, GitHub, Vercel, Supabase, or deploy
credentials for the normal OMH install path.
