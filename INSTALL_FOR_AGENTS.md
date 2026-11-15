# OMH Agent Install Protocol

Canonical install reference for AI agents and operators. Execute top to bottom,
then report the observed result. Normal users should use Hermes chat and
installed skills; `omh` is bootstrap, repair, doctor, and backend verifier
infrastructure.

## Pasteable All-In-One Request

Give an AI agent this request when you want installation and guided model setup
completed together:

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

## Prerequisites

```sh
omh_python=""
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -I -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    omh_python="$candidate"
    break
  fi
done
if [ -n "$omh_python" ]; then echo "OK: $omh_python is Python 3.11+"; else echo "MISSING: Python 3.11+"; fi
command -v git >/dev/null || echo "MISSING: git is required to resolve the pinned SHA"
command -v hermes >/dev/null || echo "NOTE: Hermes Agent command not found in PATH"
```

A bare `command -v python3` is not enough: on macOS, `/usr/bin/python3` is
Python 3.9, which OMH cannot use. A `MISSING` line blocks only the Bun, npm, uv
and pip paths. Homebrew installs its own Python with the formula, and the curl
installer also searches the usual Homebrew, python.org, pyenv and uv locations
and asks an installed `uv` for Python when it finds none.

On native Windows, run the PowerShell equivalent instead:

```powershell
$OmhPython = @('py', 'python', 'python3') | Where-Object { (Get-Command $_ -ErrorAction SilentlyContinue) -and ((& $_ -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null) -eq '1') } | Select-Object -First 1
if ($OmhPython) { "OK: $OmhPython is Python 3.11+" } else { "MISSING: Python 3.11+ is required" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { "MISSING: git is required to resolve the pinned SHA" }
if (-not (Get-Command hermes -ErrorAction SilentlyContinue)) { "NOTE: Hermes Agent command not found in PATH" }
```

If Hermes is not available, continue only when the target environment uses a
hosted wrapper that manages Hermes separately. Do not claim Hermes-visible
readiness until the target Hermes runtime or wrapper has been checked.

## Step 1: Install OMH

Use exactly one installation path, chosen by this rule:

| Machine or request | Path | Report |
| --- | --- | --- |
| Native Windows | [PowerShell installer](#native-windows) pinned to the SHA | the resolved SHA |
| macOS or Linux | [curl installer](#macos-or-linux) pinned to the SHA | the resolved SHA |
| The user asked for Homebrew, Bun, npm, uv, or pip | [that package manager](#package-managers-only-when-the-user-asks) | the version `omh --version` prints, plus the SHA for uv or pip |

The `main` URL in the pasteable request is a discovery pointer, not an
executable pin. If you fetched this file by SHA, set `OMH_REF` to that SHA
before running a block below, so the installer comes from the same revision as
this protocol. Otherwise each block resolves `main` once on its own and prints
the SHA it used. Do not mix a script from one revision with an archive from
another. The blocks never call `exit`, which would close an agent's persistent
shell; when one prints `Unable to resolve OMH main`, stop and report it.

### macOS or Linux

```sh
OMH_REF="${OMH_REF:-$(git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main | awk 'NR == 1 {print $1}')}"
if [ -z "$OMH_REF" ]; then
  echo "Unable to resolve OMH main: stop and report this"
else
  echo "OMH_REF=$OMH_REF"
  curl -fsSL "https://raw.githubusercontent.com/rlaope/oh-my-hermes/$OMH_REF/install.sh" \
    | OMH_PACKAGE_URL="https://github.com/rlaope/oh-my-hermes/archive/$OMH_REF.zip" \
      OMH_SOURCE_REF="$OMH_REF" sh
fi
```

### Native Windows

PowerShell 5.1 or later:

```powershell
$Ref = $env:OMH_REF
if (-not $Ref) { $Ref = ((git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main) -split "\s+")[0] }
if (-not $Ref) { throw "Unable to resolve OMH main" }
"OMH_REF=$Ref"
$env:OMH_PACKAGE_URL = "https://github.com/rlaope/oh-my-hermes/archive/$Ref.zip"
$env:OMH_SOURCE_REF = $Ref
irm "https://raw.githubusercontent.com/rlaope/oh-my-hermes/$Ref/install.ps1" | iex
```

The curl and PowerShell installers accept the same `OMH_*` environment contract.

### Package managers (only when the user asks)

> **Publication status:** Use the npm package and the `rlaope/tap/omh` formula
> as the package-manager distribution sources; check their official metadata
> for the version you intend to install. Publication is not runtime verification:
> it does not establish a successful install, update, or Windows CI result.

uv and pip install from the repository at the pinned SHA. Prefer uv, which puts
`omh` on PATH in its own environment:

```sh
OMH_REF="${OMH_REF:-$(git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main | awk 'NR == 1 {print $1}')}"
if [ -z "$OMH_REF" ]; then
  echo "Unable to resolve OMH main: stop and report this"
else
  echo "OMH_REF=$OMH_REF"
  uv tool install "git+https://github.com/rlaope/oh-my-hermes@$OMH_REF"
fi
```

Use pip only inside a virtual environment the user already has active. A
Homebrew or distribution Python refuses a global `pip install` with
`externally-managed-environment` (PEP 668):

```sh
OMH_REF="${OMH_REF:-$(git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main | awk 'NR == 1 {print $1}')}"
if [ -z "$OMH_REF" ]; then
  echo "Unable to resolve OMH main: stop and report this"
else
  echo "OMH_REF=$OMH_REF"
  python3 -m pip install "git+https://github.com/rlaope/oh-my-hermes@$OMH_REF"
fi
```

Both leave a PEP 610 origin record, so a later `omh update` names this owner's
upgrade command instead of the generic installer line. A uv install stays on
its pinned SHA until it is reinstalled at a new one: resolve a new ref and run
`uv tool install --force "git+https://github.com/rlaope/oh-my-hermes@<new-ref>"`.

Homebrew, Bun, and npm install the published release. They ignore the SHA, so
report the version `omh --version` prints instead:

```sh
brew install rlaope/tap/omh
bun install -g oh-my-hermes
npm install -g oh-my-hermes
```

Run only the one the user named. Bun and npm need Node 18 or later on PATH as
well as Python 3.11+: the `omh` command they install is a Node launcher, so a
Bun install without Node fails at the first `omh` call with
`env: node: No such file or directory`. Windows npm/Bun launcher support is
gated by the Windows CI suite. Without observed passing evidence for the
intended release, choose PowerShell and report Windows launcher execution as
unverified, not as unpublished.

Package-manager installs use their native global command location. Report which
path was used and verify that its `omh` command is on `PATH`.

### Run setup through the agent path

Every installation path prepares the local `omh` command only. It does not run
setup, register Hermes skill directories, install profile packs, or run doctor
by default. Run setup once as the shared, repairable, repeatable next step.

Your shell has no terminal, so do not run the interactive wizard
(`omh setup --interactive`) from it. Without a terminal on stdin, whether stdin
is closed, a pipe, or `/dev/null`, it refuses: it writes nothing, exits 1, and
prints a JSON record with `refused: true` and a `next_command`. That command is
the one you ran with `--interactive` replaced by `--no-interactive --json` and
every other flag kept. Run it instead, with the user's choices below passed as
flags.

Ask the user one question before setup, because it decides where setup writes:
**user scope** (the default: `~/.omh` and `~/.hermes` for this machine user) or
**project scope** (`.omh` and `.hermes` at the root of the git repository that
contains the current directory, not the current directory itself).

Project scope requires a git repository. Outside one, OMH falls back to the
current directory and the model step fails. When the user picks project scope,
run this once in your shell session, before any other `omh` command:

```sh
root=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$root" ]; then
  echo "project scope needs a git repository: stop and ask the user"
else
  export HERMES_HOME="$root/.hermes"
  echo "HERMES_HOME=$HERMES_HOME"
fi
```

The model step asks the `hermes` command, which reads its own `HERMES_HOME`
(default `~/.hermes`), so without the export it inspects and would write the
user's profile, the one the user just declined.

Then carry the scope through every later `omh` command in this protocol:

- `omh setup` calls take `--scope project`, for example
  `omh setup --model-setup --scope project --no-interactive --json`;
- every other command takes it as a global flag before the subcommand:
  `omh --scope project model-chains show`, `omh --scope project doctor`,
  `omh --scope project update-check set --mode off`,
  `omh --scope project coding category-maestro show`.

The commands below are written for user scope. Without the flag, each one
reads and writes `~/.omh` and `~/.hermes`.

If `command -v omh` is empty after install, use the absolute command path the
installer printed, or add that directory to `PATH`, before you run setup. Treat
this as a command availability warning, not proof that Hermes registration
failed.

Run setup without the wizard:

```sh
omh setup --model-setup --no-interactive --json
```

For project scope, run `omh setup --model-setup --scope project --no-interactive --json`.

This applies the bounded managed writes listed in
[What Setup Changes](docs/INSTALLATION.md#what-setup-changes). Those writes
register OMH with Hermes; they do not authorize model-alias changes. The run
asks nothing and writes no model config, so its
`steps.model_activation.status: defaulted` means no model has been confirmed
yet. It is where the model question starts, not the user's answer.

The model step needs the `hermes` command. When it is not on PATH, tell the user
to install Hermes Agent (or confirm the hosted wrapper that runs it), then rerun
this command; do not report setup as complete. Depending on the OMH revision,
that case returns `steps.model_activation.status: hermes_unavailable` with
`next_action: install_hermes_then_rerun_model_setup` and exit code 3, or stops
on a `FileNotFoundError` traceback naming `hermes`.

Then put each of these choices to the user, one at a time, and run the command
for the answer they give. Never record a default on the user's behalf.

| Choice | What to show the user | Command for the answer |
| --- | --- | --- |
| Update check at launch | `omh update-check status`, and the three modes: `off` (the default, no network request), `notify` (one line at launch when `main` is ahead), `auto` (also runs `omh update` at launch) | `omh update-check set --mode <off\|notify\|auto>` |
| Active models and Hermes aliases | `steps.model_activation.candidates`, and the models listed under `steps.model_activation.recommendations.hermes_native.categories.<category>.inactive_candidates` | [Guided Model Configuration](#guided-model-configuration): preview, show the digest, apply only after approval |
| Providers that serve the chains | the `Linked Hermes providers` line of `omh model-chains show` | `omh model-chains provider set <id> <kind>` for a provider whose kind is wrong or missing |
| Coding tools for handed-off work, only when `codex` or `claude` is on PATH | whether the user wants OMH to configure the detected coding CLIs | for yes, step 5 of the [Model-Chain Interview](#model-chain-interview-run-right-after-setup): `omh coding category-maestro show`, then `set`; for no, nothing |

The per-category model chains are the last choice. Ask them after Step 2, once
doctor shows no blocking check, through the
[Model-Chain Interview](#model-chain-interview-run-right-after-setup).

The agent path does not ask one wizard question, because no command records
the answer: whether the user holds a paid Claude Code subscription (asked only
when `claude` is on PATH). Its default is no subscription recorded. That only
leaves the Claude Code `--model` preference for handed-off work unset, so the
CLI keeps its own default; Hermes' models do not change. Tell the user this.
If they hold one, they can answer later by running `omh setup --interactive`
in a real terminal.

If no compatible candidate is confirmed, setup makes no model-config write,
records `status: defaulted`, and keeps the native default model of Hermes or the
selected external owner. A person at a real terminal can run
`omh setup --model-setup --interactive` instead; it asks these questions on
screen.

Expected local result (for project scope, read `<repository root>/.omh` and
`<repository root>/.hermes` for `~/.omh` and `~/.hermes`):

- generated skills are installed under `~/.omh/skills`;
- Hermes config includes that directory in `skills.external_dirs`;
- the managed plugin bridge is installed under `~/.hermes/plugins/omh`;
- normal users can talk to Hermes instead of running backend commands.

## Step 2: Verify

```sh
omh doctor
```

For project scope: `omh --scope project doctor`.

Report:

- `ok`;
- top-level `recommended_next_action`;
- whether the `command_path` check found `omh` on PATH or only an absolute path
  is available;
- any check with `severity: blocking`;
- any check with `severity: warning`;
- whether the target Hermes runtime still needs restart/reload.
- which selectors received explicit model bindings and which kept their
  owner/executor default model.

Bot profiles are synced automatically: setup and update apply the same
managed registration to every Hermes profile home under
`~/.hermes/profiles/<name>`, and a bot created later is bootstrapped by the
next `omh update`. Verify per profile with `hermes -p <name> skills list`,
and restart Hermes Desktop so bot chats reload their skills. A profile
deliberately unregistered via
`omh --hermes-home ~/.hermes/profiles/<name> uninstall --registration-only`
is never re-registered.

Bare `hermes` is stock Hermes and bare `omh` opens the OMH TUI. `omh doctor`'s
`omh_tui_support` row says whether the OMH TUI can open on this machine
(it needs a POSIX terminal and Node); where it cannot, `omh` opens Hermes'
own terminal and says why. On a machine an earlier OMH version styled,
the first setup or update prints a `Hermes display:` block naming what it
took back and where the OMH theme was saved; report that block, including
any file it kept because the user edited it.

Install success means a Hermes-usable skill path is configured and doctor has no
blocking checks. It does not mean Hermes has already reloaded the skills,
loaded the plugin bridge, executed code, reviewed a PR, passed CI, or merged.

## Package-Manager Lifecycle

`omh update` is the normal update command for every supported install path. It
detects Homebrew, Bun, npm, curl, or PowerShell provenance, upgrades the command
package through that owner, re-enters the updated command, then refreshes
managed skills, the installed plugin bundle, and existing Hermes registration.
Use the owning manager directly only as a reported repair fallback:

| Installed with | Upgrade | Remove |
| --- | --- | --- |
| Homebrew | `brew upgrade rlaope/tap/omh` | `brew uninstall omh` |
| Bun | `bun update -g --latest oh-my-hermes` | `bun remove -g oh-my-hermes` |
| npm | `npm update -g oh-my-hermes` | `npm uninstall -g oh-my-hermes` |
| uv tool (repo link) | `uv tool install --force "git+https://github.com/rlaope/oh-my-hermes@<new-ref>"` | `uv tool uninstall oh-my-hermes` |
| pip in a venv (repo link) | `python3 -m pip install --upgrade "git+https://github.com/rlaope/oh-my-hermes@<new-ref>"` | `python3 -m pip uninstall oh-my-hermes` |

Removing the command package preserves OMH state. For full cleanup, preview
`omh uninstall --all --dry-run --json` from the primary home, inspect retained
stores/failures, then run `omh uninstall --all`. Remove the command with its
owning manager only after confirming no other home needs it. Never run the curl
installer over a package-manager command to update it. An explicit
`omh update --source ...` refreshes workflow content only and does not replace
the command package, plugin bundle, or Hermes registration. Package-manager
installs reject explicit release metadata such as `--version`, `--package-url`,
or `--source-ref`; use the owning manager directly for an intentional CLI
rollback.

### Recovery and result boundaries (agent/operator reference)

Setup and update record an unset plugin store binding for both the implicit
default and a custom store. Selecting `--hermes-home <profile>` alone can resolve
that profile's store; an explicit `--omh-home` selects a target, not permission
to delete shared data. Existing user bindings remain unchanged.

Registration-only removes managed skill entries by real path, including the
primary skill store A even when the profile selects a different runtime store B.
It also recognizes a configured runtime store's managed skills candidate; an
arbitrary external directory is never owned just because its basename is
`skills` or `omh`. It preserves store data, plugin files and plugin enablement:
it does not disable the plugin. Desktop mounting must be observed separately.
The remaining plugin directory plus absent managed registration is the opt-out
marker; the next sync leaves that profile unregistered.

Before destructive store cleanup, OMH inventories persisted primary/sibling
home settings and skill registrations. A targeted profile using a shared store
gets a profile-local detach: its managed integration is removed, but the store,
records and shared command remain. `--all` / `--purge` are full-cleanup aliases,
not overrides for this guard; from the primary home they include its profiles.
`--remove-files` uses the same store guard without full integration cleanup.
A genuinely unshared store can be removed. Full primary cleanup detaches children
before deleting shared roots, then re-reads the actual retained references. A
readable config is not proof that its guarded rewrite will succeed: if a child
refuses detach (including a readable symlinked config), the store, records and
shared command remain and the result is partial/nonzero. User-edited retained
bindings or skill registrations also protect the store and command.
`--dry-run --json` writes nothing and conservatively keeps roots still referenced
by children; it does not assume planned detach succeeded. Inspect `store_removal`,
`kept_paths`, `hermes_profiles` and `would_remove`.

An unreadable config, invalid UTF-8, unreadable profile inventory, or a persisted
`.env` naming `OMH_HOME` without a winning config binding makes ownership unknown.
OMH reports `unreadable_reference_inventory`, exits nonzero and leaves config,
store and managed artifacts untouched for that blocked cleanup. Repair the named
home or record its intended absolute `plugins.entries.omh.settings.omh_home`
before retrying; do not delete a store manually to bypass the refusal. Inventory
does not count another home's transient process environment as a persisted
reference, and cannot prove that no external process is using the store.

For normal managed refresh, `omh update --json` emits exactly one final JSON
document after plugin, registration and profile processing, preserving existing
install fields. Inspect `hermes_profiles` for refreshed, bootstrapped,
`host_managed`, `unregistered_kept` and failed rows, not just installed skills.
An unreadable/invalid-UTF-8 or protected profile is named as failed; later healthy
profiles still synchronize, without rewriting the unreadable config. A required
refresh failure produces `status: partial`, `failures`, `exit_code: 1` and a
nonzero process exit; the human summary names the failure rather than claiming
completion. Repair the named profile's permissions/config or review protected
local edits before retrying; never discard them merely to make a status green.

For the primary plugin only, `update --dry-run` can return a successful plan
with `plugin_bundle.status: would_refuse`, `applied: false`, and a `reason`
when a readable, structurally valid OMH manifest confirms dirty managed files
or unknown private entries. This is not an applied refresh: it writes nothing,
and an actual refused update remains partial/nonzero. Missing, unreadable or
malformed manifest inventories and real inspection/config errors are not
protected-only plans; required child-profile failures still make dry-run
partial/nonzero. Hermes-owned plugins remain host-managed, even with `--force`.

Explicit `--source` / `--from-skills-dir` updates remain workflow-content-only:
no command-package replacement, plugin refresh or Hermes registration/profile
sync is implied. Optional menubar handling is not required-profile success.

Command cleanup accepts proven installer-owned legacy and `generations` venvs,
`current` and managed launchers, not foreign or package-manager command roots.
Named-profile uninstall retains the shared command; `--keep-command` preserves
it even during primary cleanup. Verify retained paths before removing anything
through the owning manager.

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

If the target Hermes environment supports skill taps and the user wants it,
this is the native front door:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

Use the full identifier. A short name can resolve to another tap's skill. The
router skill's directory and its frontmatter name are both `omh-routing`.

The tap is an alternative to `omh setup`, not an addition to it. A tap install
lands in the Hermes home's own skills directory, which Hermes 0.21.6 and later
rank above the `skills.external_dirs` entry OMH manages, so on a machine that
also runs `omh setup` the tap copy hides the managed skill; older hosts refuse
the shared name as ambiguous instead. Either way the tap copy never receives
an OMH update. `omh doctor` names such a copy under `identity_conflicts`.

Install direct workflow skills only when the user wants them exposed as explicit
Hermes skill choices:

```sh
hermes skills install rlaope/oh-my-hermes/skills/ulw-interview --yes
hermes skills install rlaope/oh-my-hermes/skills/ulw-plan --yes
hermes skills install rlaope/oh-my-hermes/skills/ulw-research --yes
hermes skills install rlaope/oh-my-hermes/skills/omh-feedback-triage --yes
hermes skills install rlaope/oh-my-hermes/skills/omh-ops-review --yes
hermes skills install rlaope/oh-my-hermes/skills/omh-code-review --yes
```

The tap path and `omh setup` path should converge on the same user experience:
Hermes can see OMH guidance and the user talks to Hermes.

## Other Agent Hosts

OMH's workflow guidance can also be installed as Agent Skills for Claude Code,
Codex, Cursor, opencode, OpenClaw, and pi. That is a separate install that
needs no Hermes and does not replace Step 1. When the user asks for it, follow
[Agent Skills projection](docs/AGENT-SKILLS.md): clone the repository, check out
the SHA you resolved, then run that one host's `install.sh` (or `install.ps1` on
native Windows) from the target project's root.

## Plugin Bridge And Profile Packs

`omh setup` installs `~/.hermes/plugins/omh` and lets doctor verify local
manifest, import, and register smoke checks. It does not patch Hermes core,
implement Discord or Slack transports, start a network service, or prove Hermes
loaded the plugin. Runtime plugin use must be observed separately.

Profile packs are setup choices, not curl-download choices. Add them when setup
runs:

```sh
omh setup --profile-pack cto-loop
```

## Guided Model Configuration

The all-in-one request explicitly opts into this step. Model configuration is
still not required for OMH installation, and a missing shipped recommendation
must not turn install or doctor into a failure.

Setup seeds the user's chain-customization document at
`~/.omh/routing/model-chains.json` (`mixture_chain_overrides/v1`, empty
`categories` = shipped defaults apply). Tell the user this file is where they
reorder or replace a category's model chain later without touching code; a
category written there governs routing, fallback, and HUD labels. Example:

```json
{
  "schema_version": "mixture_chain_overrides/v1",
  "categories": {
    "quick": [
      {"model": "glm-5.3-flash", "reasoning_effort": "low"},
      {"model": "kimi-k3.1-pro", "reasoning_effort": "low"}
    ]
  }
}
```

Use this exact agent-facing prompt:

```text
Inspect my bounded local model metadata and help me configure OMH model routing. Ask me to confirm which models are still active. Keep Hermes-native aliases separate from Maestro external handoffs, show the exact alias preview and config digest before any write, and apply only after I approve it. Keep recommendation categories editable; if Kimi, GPT, or Claude is missing, continue with a confirmed compatible model such as Qwen or Gemini. If no compatible recommendation is confirmed, keep that selector on its owner's native default model and finish setup without a model-config write. Explain Grok's editorial X-platform affinity without presenting it as measured performance. Treat CCAPI and Apitopia as user-declared editorial provider preferences only. Do not read, copy, request, or echo credentials.
```

Agent/maintainer procedure:

1. Show the user the bounded local observations from the Step 1 setup run
   (`steps.model_activation`) and confirm active models with them.
   A session-history observation is `observed_before`, not active confirmation.
2. Build a Hermes-native alias preview without applying it. Repeat
   `--confirm-model` and `--model-alias` as needed. For project scope, keep
   `HERMES_HOME` exported and add `--scope project`, here and on the apply
   call in step 3; without it the preview runs a full user-scope setup:

   ```sh
   omh setup --model-setup \
     --confirm-model google/gemini-4-argon \
     --model-alias main=google/gemini-4-argon \
     --no-interactive --json
   ```

   A target whose provider has no Hermes login is refused with
   `lacks safe observed provider auth`; the user links that provider with
   `hermes auth` first, then you repeat the preview. A provider configured
   under Hermes `providers:` counts once its key is observable: the refusal
   `is configured under providers: but no credential is observable` names the
   environment variable it reads (its `key_env`), and the user sets that
   variable in the shell OMH runs in, or adds a pool with
   `hermes auth add <id>`, then you repeat the preview.

3. Show the user `steps.model_activation.preview.changes` and
   `config_digest`. After explicit approval, repeat the command with
   `--apply-model-config --model-config-digest <preview-digest>`. A collision
   requires a separate explicit `--allow-model-alias-collision` choice.
   If no candidate is confirmed and no alias is requested, verify
   `steps.model_activation.status == "defaulted"` and that no model-config
   change was prepared or applied.
4. For an approved write, verify
   `steps.model_activation.verification.status == "verified"`, then run
   the offline agent/maintainer report:

   ```sh
   omh coding model-routing status --json
   ```

Hermes aliases are written through Hermes' native `config` commands. Maestro is
an OMH-local coordinator for prepared external coding-CLI handoffs (Codex,
Claude Code, the supported runtime profiles, and generic executors); it is not
an executor and does not own Hermes-native work. Recommendations are
editable editorial metadata, not provider availability or benchmark evidence.
Qwen, Gemini, or another confirmed compatible model can be selected when a
shipped recommendation is absent. When none is confirmed, `owner_default`
means the relevant native owner keeps choosing its default model; it does not
prove which model that owner will use. Grok's `x_platform_data` position is an
editable X-platform affinity only. CCAPI and Apitopia are never probed; their
entries remain user-declared provider-family preferences, and credentials stay
in their native owner.

## Model-Chain Interview (Run Right After Setup)

The setup summary ends by recommending the per-category model chains. For an
agent-driven install this recommendation is part of the protocol, not optional
advice: once `omh setup` succeeds and doctor has no blocking checks, run
the chain interview with the user before reporting the install complete.

`omh model-chains interview` is the human terminal path and refuses non-TTY
sessions with a scriptable-path message. Agents conduct the same interview in
conversation. For project scope, put `--scope project` before the subcommand
of every command below (`omh --scope project model-chains show`):

1. Run `omh model-chains show` and present the current state per category
   (chain order plus origin: `default` or `override`).
2. For each category the user wants to adjust, offer numbered options:
   `1` keep current, `2` shipped default (when overridden), `3` provider speed
   variant (for example an Ultrafast tier) when one exists for the chain,
   `4` custom entry the user types.
3. Apply choices with `omh model-chains set <category> "model[:effort], ..."`,
   or edit `~/.omh/routing/model-chains.json` directly — both write the same
   `mixture_chain_overrides/v1` document.
4. Re-run `omh model-chains show` and report the confirmed state.
5. When a `codex` or `claude` CLI is detected on PATH, offer the Maestro
   lane's own category table the same way: `omh coding category-maestro show`
   presents the effective table per dispatchable profile, and
   `omh coding category-maestro set <profile> <category> <model[:effort]>...`
   is the scriptable write (`omh coding category-maestro interview` is the
   human terminal path and refuses non-TTY sessions). This table routes
   `omh coding run --category <c>` and fanout units that declare a
   `category`; an explicit `--model` always outranks it, and skipping this
   step keeps the built-in defaults.

If a chain alias needs a provider-specific wire model, edit the sibling
`~/.omh/routing/model-providers.json` document:

```json
{"schema_version":"model_provider_routes/v1","models":{"glm-5.3":{"provider":"opengateway","model":"z-ai/glm-5.3"}}}
```

From a shell, run `omh model-chains show --json` and report `routes_status`:
`absent` means there is no `model-providers.json` and every alias dispatches
unchanged; `applied` means OMH read the document; an `invalid: ...` value names
the reason, and the whole document is ignored. No shell command resolves the full route. Inside a Hermes chat,
Hermes can call its `omh_delegate_route` tool with `action=status` and report
the complete alias/provider/model/effort route; an agent working from Claude
Code, Codex, or another shell reports the route as not observed. Provider and
model overrides are atomic; never copy credentials into OMH.

A user who declines the interview keeps the shipped defaults; record that as
the observed result instead of skipping the step silently.

## First Hermes Prompt

After install and any required Hermes restart/reload, try:

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

Expected behavior:

- Hermes explains why `request-to-handoff` is the right first workflow;
- Hermes names the responsible role such as `planner` or
  `handoff-guide`;
- Hermes gives the next action, such as clarify, accept plan, choose executor,
  or show status;
- Hermes keeps prepared handoff separate from observed execution evidence.

## Failure Report Template

```text
OMH install result:
- install command:
- omh setup output summary:
- omh doctor ok:
- model-chain interview result:
- recommended_next_action:
- blocking checks:
- warning checks:
- Hermes restart/reload performed:
- first Hermes prompt tried:
- observed Hermes response:
```

Do not ask the user for Discord, Slack, GitHub, Vercel, Supabase, or deploy
credentials for the normal OMH install path.
