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
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

## Prerequisites

```sh
command -v python3 >/dev/null || echo "MISSING: python3 is required"
command -v git >/dev/null || echo "MISSING: git is required for source installs"
command -v hermes >/dev/null || echo "NOTE: Hermes Agent command not found in PATH"
```

On native Windows, run the PowerShell equivalent instead:

```powershell
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { "MISSING: Python 3.11+ is required" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { "MISSING: git is required for source installs" }
if (-not (Get-Command hermes -ErrorAction SilentlyContinue)) { "NOTE: Hermes Agent command not found in PATH" }
```

If Hermes is not available, continue only when the target environment uses a
hosted wrapper that manages Hermes separately. Do not claim Hermes-visible
readiness until the target Hermes runtime or wrapper has been checked.

## Step 1: Install OMH

> **Publication status:** Package-manager installs are pending the first distribution release.
> Until npm and the Homebrew tap are public, choose curl or PowerShell and report
> that package-manager publication is not yet observed.

Homebrew:

```sh
brew install rlaope/tap/omh
```

Bun (recommended):

```sh
bun install -g oh-my-hermes
```

npm:

```sh
npm install -g oh-my-hermes
```

The `main` URL in the pasteable request is a discovery pointer, not an
executable pin. Before running repository code, resolve `main` once and use the
same immutable commit SHA for both the installer and source archive. Report the
resolved SHA. Do not mix a script from one revision with an archive from
another.

Universal installer on macOS or Linux:

```sh
OMH_REF="$(git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main | awk 'NR == 1 {print $1}')"
if [ -z "$OMH_REF" ]; then echo "Unable to resolve OMH main"; exit 1; fi
curl -fsSL "https://raw.githubusercontent.com/rlaope/oh-my-hermes/$OMH_REF/install.sh" \
  | OMH_PACKAGE_URL="https://github.com/rlaope/oh-my-hermes/archive/$OMH_REF.zip" \
    OMH_SOURCE_REF="$OMH_REF" sh
```

Direct pip or uv install from the repository (for agents handed only the
repository link) — pin the same resolved SHA:

```sh
python3 -m pip install "git+https://github.com/rlaope/oh-my-hermes@$OMH_REF"
# or, isolated on PATH:
uv tool install "git+https://github.com/rlaope/oh-my-hermes@$OMH_REF"
```

Both leave a PEP 610 origin record, so a later `omh update` names the exact
upgrade command for this owner (`pip install --upgrade "git+..."` or
`uv tool upgrade oh-my-hermes`) instead of the generic installer line.

Native Windows (PowerShell 5.1+):

```powershell
$Ref = ((git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main) -split "\s+")[0]
if (-not $Ref) { throw "Unable to resolve OMH main" }
$env:OMH_PACKAGE_URL = "https://github.com/rlaope/oh-my-hermes/archive/$Ref.zip"
$env:OMH_SOURCE_REF = $Ref
irm "https://raw.githubusercontent.com/rlaope/oh-my-hermes/$Ref/install.ps1" | iex
```

Windows npm/Bun launcher support is gated by the Windows CI suite. Until the
first package-manager release passes that gate, choose PowerShell and report
the npm/Bun path as prepared but not yet published.

The curl and PowerShell installers accept the same `OMH_*` environment contract.
Package-manager installs use their native global command location. Report which
path was used and verify that its `omh` command is on `PATH`.

Every installation path prepares the local `omh` command only. It does not run
setup, register Hermes skill directories, install profile packs, or run doctor
by default. Run setup once as the shared, repairable, repeatable next step:

```sh
omh setup --model-setup --interactive
```

The interactive model step asks the user to confirm active candidates and
previews any Hermes-native alias change before approval. If no compatible
candidate is confirmed, setup makes no model-config write, records
`status: defaulted`, and keeps the native default model of Hermes or the
selected external owner.

Core setup separately applies the bounded managed writes listed in
[What Setup Changes](docs/INSTALLATION.md#what-setup-changes). Those writes
register OMH with Hermes; they do not authorize model-alias changes.

If `command -v omh` is still empty after install, use the absolute command path
printed by the installer or add that directory to `PATH`, then continue with
doctor. Treat this as a command availability warning, not proof that Hermes
registration failed.

Expected local result:

- generated skills are installed under `~/.omh/skills`;
- Hermes config includes that directory in `skills.external_dirs`;
- the managed plugin bridge is installed under `~/.hermes/plugins/omh`;
- normal users can talk to Hermes instead of running backend commands.

## Step 2: Verify

```sh
omh doctor
```

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

Setup and update end with an `OMH TUI:` verdict line. Act on it before
reporting success: `ready` means the OMH look applies on the next Hermes
start (restart any running session; the styled TUI opens with `omh` or
`hermes --tui`). A blocked verdict lists each blocker with its fix — most
commonly an old Hermes without the TUI widget loader, whose fix is running
`hermes update` (Hermes' own updater; OMH never runs it for the user) and
then restarting Hermes. Report the verdict and any fix you ran.

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
| pip (repo link) | `pip install --upgrade "git+https://github.com/rlaope/oh-my-hermes"` | `pip uninstall oh-my-hermes` |
| uv tool (repo link) | `uv tool upgrade oh-my-hermes` | `uv tool uninstall oh-my-hermes` |

Removing the command package preserves OMH state. For full cleanup, run
`omh uninstall --all` before the manager's remove command. Never run the curl
installer over a package-manager command to update it. An explicit
`omh update --source ...` refreshes workflow content only and does not replace
the command package, plugin bundle, or Hermes registration. Package-manager
installs reject explicit release metadata such as `--version`, `--package-url`,
or `--source-ref`; use the owning manager directly for an intentional CLI
rollback.

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
hermes skills install research
hermes skills install feedback-triage
hermes skills install ops-review
hermes skills install code-review
```

The tap path and `omh setup` path should converge on the same user experience:
Hermes can see OMH guidance and the user talks to Hermes.

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
      {"model": "kimi-k3-ultrafast", "reasoning_effort": "low"},
      {"model": "glm-5.2-ultrafast", "reasoning_effort": "low"}
    ]
  }
}
```

Use this exact agent-facing prompt:

```text
Inspect my bounded local model metadata and help me configure OMH model routing. Ask me to confirm which models are still active. Keep Hermes-native aliases separate from Maestro external handoffs, show the exact alias preview and config digest before any write, and apply only after I approve it. Keep recommendation categories editable; if Kimi, GPT, or Claude is missing, continue with a confirmed compatible model such as Qwen or Gemini. If no compatible recommendation is confirmed, keep that selector on its owner's native default model and finish setup without a model-config write. Explain Grok's editorial X-platform affinity without presenting it as measured performance. Treat CCAPI and Apitopia as user-declared editorial provider preferences only. Do not read, copy, request, or echo credentials.
```

Agent/maintainer procedure:

1. Preview bounded local observations and confirm active models with the user.
   A session-history observation is `observed_before`, not active confirmation.
2. Build a Hermes-native alias preview without applying it. Repeat
   `--confirm-model` and `--model-alias` as needed:

   ```sh
   omh setup --model-setup \
     --confirm-model google/gemini-3.1-pro \
     --model-alias main=google/gemini-3.1-pro \
     --no-interactive --json
   ```

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
an OMH-local coordinator for prepared external Codex, Claude Code, OMO, OMC,
OMX, and generic handoffs; it is not an executor and does not own Hermes-native
work. `pi` and `senpi` are OMO runtime-family hosts. Recommendations are
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
advice: once `omh setup` succeeds and the `OMH TUI:` verdict is handled, run
the chain interview with the user before reporting the install complete.

`omh model-chains interview` is the human terminal path and refuses non-TTY
sessions with a scriptable-path message. Agents conduct the same interview in
conversation:

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

If a chain alias needs a provider-specific wire model, edit the sibling
`~/.omh/routing/model-providers.json` document:

```json
{"schema_version":"model_provider_routes/v1","models":{"glm-5.2-ultrafast":{"provider":"opengateway","model":"z-ai/glm-5.2-ultrafast"}}}
```

Re-run `omh_delegate_route` with `action=status` and report its complete
alias/provider/model/effort route. Provider and model overrides are atomic;
never copy credentials into OMH.

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
