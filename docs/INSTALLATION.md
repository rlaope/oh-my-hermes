# Installation

This guide is for people and operators who want Hermes Agent to see the OMH
skill pack. Normal users should talk to Hermes through Hermes' skill and chat
surfaces. Their direct OMH command surface is normally limited to `omh setup`,
`omh update`, and `omh doctor`. The broader CLI is deterministic backend
infrastructure for Hermes Agent, wrappers, coding agents, automation, and
maintainers.

AI agents and operators who need a pasteable protocol should use the root
[Agent Install Protocol](../INSTALL_FOR_AGENTS.md). That protocol defines what
to run, what to report, and what is still unobserved after install.

## Command Audience

| Audience | Normal interaction |
| --- | --- |
| Person using Hermes | Ask Hermes for the result in natural language. Run `omh setup`, `omh update`, or `omh doctor` only for local maintenance. |
| Hermes Agent or wrapper | Route requests and call structured chat, coding, runtime, memory, and evidence commands behind the conversation. |
| Coding agent or automation | Consume prepared contracts, record observed evidence, and run scoped control-plane commands. |
| Maintainer or advanced operator | Inspect catalogs, harnesses, release checks, fixtures, and machine-readable payloads. |

Commands outside the three human defaults can still be run manually for
integration, debugging, or maintenance. When this guide shows them, treat them
as agent, wrapper, operator, or maintainer references rather than prerequisites
for using OMH.

## Quick Start

> **Publication status:** Homebrew, Bun, and npm package-manager installs are
> public as of v1.0.6. Clean installation and `omh update` were observed for
> each package-manager path in isolated release QA.

Choose one installation path. The package-manager paths install the same `omh`
command as the platform installers.

### Homebrew

```sh
brew install rlaope/tap/omh
```

### Bun (recommended)

```sh
bun install -g oh-my-hermes
```

### npm

```sh
npm install -g oh-my-hermes
```

### Universal installer (macOS/Linux)

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

### Windows (PowerShell 5.1+)

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

Windows npm/Bun launcher support is covered by the Windows CI suite, including
packed-tarball installation and CLI smoke checks. The PowerShell installer
remains the native Windows alternative.

### Set up OMH

After any installation path, install the managed skills and register them with
Hermes:

```sh
omh setup
```

### Keep every installed layer current

The same command updates every supported installation path:

```sh
omh update
```

For Homebrew, Bun, and npm installs, the launcher records the owning package
manager. `omh update` runs that manager's native upgrade first, then re-enters
the newly installed `omh` command. The curl and PowerShell installers use the
same flow through their isolated managed virtual environment. After the command
package succeeds, the re-entered command refreshes managed skills, an already
installed plugin bundle, and existing Hermes registration.

On a machine that never completed `omh setup`, `omh update` bootstraps the
full OMH TUI surface instead of skipping it: it installs the plugin bundle,
registers and enables OMH in the Hermes config (activating the skin), installs
the TUI widget, and seeds `~/.omh/routing/model-chains.json` — update and
setup converge on the same machine state. One deliberate opt-out is honored:
after `omh uninstall --registration-only` the plugin directory stays in place,
so update never re-registers a machine whose owner removed the registration
on purpose.

An explicit `--source` or `--from-skills-dir` remains a workflow-content-only
operation, and `--dry-run` never changes the command package. A source checkout
or other unmanaged Python environment is not rewritten implicitly; the result
reports the supported installer command instead.

### Verify or troubleshoot the installation

Run doctor separately after setup:

```sh
omh doctor
```

First-run expectation:

1. Your chosen package manager or installer exposes the `omh` command.
2. `omh setup` installs the managed skills and records safe defaults.
3. `omh doctor` checks local registration and points to the next repair action.
4. You restart or reload Hermes Agent.
5. You ask Hermes normally, for example: `I want to safely add a feature to this repo.`

By default, `omh setup` installs the **full** skill profile: every packaged
skill, the ULW engines included — installing OMH means getting OMH. Pass
`--core` for the lightweight footprint (the doctor health floor plus the
chat/plan/status/handoff essentials); see
[Skill Profiles: Core vs Full](#skill-profiles-core-vs-full) for the
context-weight trade-off each choice makes.

You do not need to know or name a workflow. The quickstart card offers
representative natural-language starters from the locally tested request corpus
and tells the wrapper which workflow and next action each starter should expose.
An adapter that needs an explicit workflow can still use
`Use OMH request-to-handoff for: I want to safely add a feature to this repo.`

First-value packs are the stronger first-use paths once setup is done:

- **Frontend Rescue** for natural frontend layout, anti-AI polish, responsive
  repair, accessibility checks, and visual QA handoff.
- **Repo First-Win** for mapping a new repository and finding the first safe
  valuable improvement.
- **Failure-to-Fix** for failing deploys, Pages, CI, DCO, builds, and tests.
- **Visual Deliverable** for polished PR, release, report, deck, PDF, or image
  summary packages.
- **Toolbelt Readiness** for local CLIs, MCP hosts, credentials, connectors,
  and executor runtime readiness.
- **CTO/Product Loop** for roadmap, architecture, launch, QA, security, and
  operations tradeoff review.

These packs prepare routes, handoffs, and evidence boundaries. They do not
claim execution, visual QA, CI, deployment, publication, credential validity, or
merge evidence until Hermes or the selected runtime observes those steps.

If the next step is still unclear, ask Hermes:

```text
what should I do next with OMH setup?
```

Hermes/wrappers can answer with the same compact quickstart card without asking
for shell command approval. The backend command is:

```sh
omh quickstart
```

`omh quickstart` prints the compact first-use card instead of a deep diagnostic
dump. It reads the current doctor/probe state, suggests the next Hermes chat
prompt, and separates local readiness from evidence that still has to be
observed by Hermes or a wrapper. The JSON form is `omh_quickstart_card/v1` and
is the same card that `omh chat interact` returns as
`chat_response.kind == quickstart` for setup/first-use questions:

```sh
omh quickstart --json
```

If the user asks what OMH is or how to use it, wrappers can answer with
`chat_response.kind == context_brief` and `[omh] context` before opening the
full workflow picker. This keeps the first explanation conversational while
still exposing `omh_context_brief/v1` for adapters that want structured lanes,
rules, and boundaries.

## Guided Model Setup

Normal users can ask Hermes **set up my models**. The CLI in this section is an
**agent/maintainer** configuration and diagnosis surface, not a prerequisite for
installing or using OMH.

The guided flow is deliberately staged:

1. **Inspect.** `omh setup --model-setup` scans bounded, allowlisted metadata
   roots for Codex, Claude Code, Hermes, OpenCode, OMO, `pi`, and `senpi`.
   `pi` and `senpi` are host CLIs in the OMO runtime family. Discovery does not
   open auth files or call providers. It parses bounded local session/config
   records, which may contain prompt or tool-result fields, but emits only the
   allowlisted provider, model, variant, timestamp, and source identifiers; it
   never returns or persists transcript prose or credential values.
2. **Confirm active.** Prior session/config metadata is only `observed_before`.
   A model becomes `confirmed_active` for this flow only through an explicit
   `--confirm-model PROVIDER/MODEL` choice. This is still user-declared local
   configuration, not entitlement, credential validity, quota, or execution.
3. **Preview.** Repeated `--model-alias ALIAS=MODEL` values produce exact Hermes
   `model.aliases` changes and a digest-bound preview. Existing aliases remain
   user-owned; collisions fail closed unless separately allowed.
4. **Apply.** No preview writes. An apply requires both
   `--apply-model-config` and the preview's `--model-config-digest`; an
   interactive flow asks after showing the preview. Hermes' own `config set`
   command owns the mutation.
5. **Verify.** The adapter re-inspects the native Hermes alias and reports a
   verified receipt. Preview, apply, and verification remain separate states.

Agent/maintainer preview example:

```sh
omh setup --model-setup \
  --confirm-model openrouter/qwen3-coder \
  --confirm-model google/gemini-3.1-pro \
  --model-alias main=openrouter/qwen3-coder \
  --no-interactive --json
```

Show the resulting `steps.model_activation.preview.changes` and
`config_digest` to the user. Apply only after approval by repeating the same
arguments with:

```sh
--apply-model-config --model-config-digest <preview-digest>
```

An explicit unavailable model returns `choice_required` and never silently
falls through. A missing recommended model is different: setup remains usable
and ordered recommendation chains skip missing entries in favor of a confirmed
compatible alternative. Qwen and Gemini therefore remain valid user-selected
alternatives even when they are not shipped category heads. If no candidate is
confirmed for the selected category, role-slot, and domain chains, the resolver
consults one shared final order: Claude Opus 5, then GPT-5.6 Sol. These names
remain editorial candidates filtered through caller-confirmed metadata; they
do not prove subscription, entitlement, authentication, or runtime readiness.
If no candidate is confirmed anywhere, the resolver records `owner_default`;
Hermes or the selected external owner keeps its native default model, setup
completes with `status: defaulted`, and no model-config write is prepared or
applied.

### Editable recommendation categories

The shipped catalog is editorial policy, not benchmark output:

| Surface | What it is for | Shipped editable order |
| --- | --- | --- |
| Hermes `main` suggestion | The session's own model | Kimi K3, Claude Opus 5, Claude Fable 5, GPT-5.6 Sol, GPT-5.6 Terra |
| `ultrabrain` | Deepest reasoning | GPT-5.6 Sol (`xhigh`) |
| `deep` | Strong default tier | GPT-5.6 Terra, DeepSeek V3.2 (`high`) |
| `architect` | Architecture and system design | Claude Fable 5, GPT-5.6 Sol, Kimi K3 (`xhigh`) |
| `unspecified-high` | Default working model | Kimi K3, Claude Opus 5 |
| `unspecified-low` | Cheaper fallback | GLM 5.2, GLM 5.2 Ultrafast, DeepSeek V3.2, Claude Opus 5 (low) |
| `visual-engineering` | Frontend and visual | Claude Fable 5, Kimi K3 |
| `quick` | Short tasks | GLM 5.2 Ultrafast, Kimi K3, GPT-5.6 Luna, Claude Fable 5 (low) |
| `writing` | Prose and docs | Kimi K3, Qwen3-Coder, Gemini 3.1 Pro |
| `artistry` | Unconventional work | Gemini 3.1 Pro, Claude Fable 5, Kimi K3 |
| `x_platform_data` affinity | X-platform data affinity | Grok, Kimi K3, Gemini |
| Shared final order (`last_resort.any`) | Last resort when a chain is exhausted | Claude Opus 5, GPT-5.6 Sol |

Chain customization is a config edit, not a source edit — `omh model-chains
show` prints the current per-category state, `omh model-chains interview`
walks every category with numbered choices on a terminal, and
`omh model-chains set <category> "model[:effort], ..."` is the scriptable
write (agents included). All of them edit the same document: `omh setup` seeds
`~/.omh/routing/model-chains.json` (`mixture_chain_overrides/v1`) with an
empty `categories` object, meaning the shipped defaults above stay live and
keep updating with `omh update`. A category written into that file replaces
its whole chain — for delegation routing, `omh_delegate_route` fallback
walks, and HUD category labels alike — until the user removes it. An invalid
document is ignored whole (defaults apply) and reported by
`omh_delegate_route` `action=status` as `chain_overrides: invalid: ...`.

### Reaching models through a provider

Chains name models the way a person says them (`glm-5.2`, `kimi-k3`). A host
that reaches models through a provider usually needs two different values
instead: a provider id, and that provider's own model string, which is often
namespaced like `vendor/model-name`. Which provider serves which model, and
under what name, belongs to one account — so OMH ships no routes and hardcodes
no provider.

Supply them in `~/.omh/routing/model-providers.json`
(`model_provider_routes/v1`), a sibling of the chain document:

```json
{
  "schema_version": "model_provider_routes/v1",
  "models": {
    "glm-5.2": {"provider": "my-gateway", "model": "z-ai/glm-5.2"},
    "kimi-k3": {"provider": "my-gateway", "model": "moonshotai/kimi-k3"}
  }
}
```

An alias listed here dispatches as that provider's model; an alias not listed
dispatches unchanged with no provider, which is what a direct-billing host
wants — the file is optional and absent by default. A `provider` passed
explicitly with its wire `model` to `omh_delegate_route` outranks any stored
route. Provider and model change atomically; partial pairs and providerless
wire-shaped models fail before Hermes config is mutated. Fallback translates
an active exact provider/wire pair back to one alias and requires the category
when that alias has multiple chain origins. Validation is strict, token-only,
and atomic: an invalid file is reported by `action=status` and blocks set or
fallback rather than silently inheriting a parent provider.

`action=status` and fallback results expose the complete
`alias`/`provider`/`model`/`reasoning_effort` shape. HUD rows use the same
configured mapping for labeling and mark the provider source as
`model_provider_routes`; that configured metadata is not provider execution
or credential evidence.

The X/Grok row is a static, editable affinity for work explicitly declaring X
platform data. It is not a measured capability, performance, or availability
claim, never removes another candidate, and never overrides an explicit user
choice. CCAPI for Claude and Apitopia for Kimi are preferred provider-family
metadata only. They are not bundled or probed integrations and are considered
only when the user declares the corresponding local route active. OMH never
copies their tokens or keys.

Agents and maintainers can replace named chains with a secret-free
`model_recommendation_overrides/v2` JSON file. Only the existing category,
`main` role, `x_platform_data` domain, and shared `last_resort.any` keys are
accepted; named chains replace rather than merge with shipped order. Legacy v1
documents remain accepted but cannot define `last_resort`. For example:

```json
{
  "schema_version": "model_recommendation_overrides/v2",
  "categories": {
    "deep": [
      {
        "model_alias": "qwen3-coder",
        "model_family": "qwen",
        "preferred_provider_families": ["openrouter"],
        "reasoning_effort": "high",
        "reasoning": "Local editorial choice for this installation."
      }
    ]
  },
  "last_resort": {
    "any": [
      {
        "model_alias": "claude-opus-5",
        "model_family": "claude",
        "preferred_provider_families": ["anthropic"],
        "reasoning": "Local final metadata selection."
      }
    ]
  }
}
```

The agent/maintainer routing preview accepts it with
`omh coding model-route --executor hermes --from-inventory --recommendations
/path/to/overrides.json --json`. Override files cannot carry credential,
secret, token, password, or provider-configuration fields.

### Hermes-native and Maestro ownership

Hermes-native routing resolves a reviewed alias/provider/model binding and
keeps native skill, Kanban, and `delegate_task` execution in Hermes. It does
not cross Maestro.

Maestro is the external handoff boundary for Codex, Claude Code, OMO, OMC, OMX,
and generic profiles. It projects an ordered eligible recommendation chain,
coordinates existing prepared handoff/status adapters, and rejects Hermes as an
external profile. Maestro does not execute work, write Hermes aliases, own
credentials, or convert a prepared handoff into observed evidence. External
owner observations must still be recorded by the selected executor or wrapper.

For offline diagnosis, agents and maintainers can run:

```sh
omh coding model-routing status
omh coding model-routing status --json
```

The report separates confirmed models from discovered-only metadata, Hermes
aliases from Maestro category readiness, and owner-learning state from both.
Its missing recommendation heads are advisory. To clear only one learned owner
preference, an agent/maintainer may run `omh coding model-routing reset
--route-family <id>`; this does not alter aliases, recommendations, providers,
or credentials.

## Windows

OMH runs natively on Windows. The full test suite is an enforcing CI gate on
`windows-latest`, not a smoke subset, so the library itself is held to the same
standard as macOS and Linux. What follows is the install path, the config-home
answer, and the capability boundary.

### Install

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
omh doctor
```

`install.ps1` is the PowerShell counterpart of `install.sh`. It reads the same
`OMH_*` environment contract, resolves the package source the same way, and
hands `omh setup` the same arguments. It requires Windows PowerShell 5.1
(shipped with Windows 10 and 11) or newer.

If you would rather not pipe a remote script into `iex`, the manual path is
equivalent — this is what the installer automates:

```powershell
py -m venv $env:LOCALAPPDATA\omh\venv
& $env:LOCALAPPDATA\omh\venv\Scripts\python.exe -m pip install --upgrade `
    https://github.com/rlaope/oh-my-hermes/releases/download/v<version>/oh_my_hermes-<version>-py3-none-any.whl
& $env:LOCALAPPDATA\omh\venv\Scripts\omh.exe setup
```

The installer resolves `<version>` for you from the `releases/latest` redirect.
Doing it by hand means naming the release you want.

Where it differs from `install.sh`, it differs because the platform does:

| Behavior | POSIX | Windows |
| --- | --- | --- |
| Default venv | `~/.local/share/omh/venv` | `%LOCALAPPDATA%\omh\venv` |
| Default command dir | `~/.local/bin` | `%LOCALAPPDATA%\omh\bin` |
| How `omh` is exposed | symlink | `omh.cmd` shim (a symlink needs Developer Mode or elevation) |
| PATH | hint printed | appended to the user PATH; set `OMH_ADD_TO_PATH=0` for hint-only |

`OMH_ADD_TO_PATH` is the one option `install.ps1` adds. On POSIX,
`~/.local/bin` is a convention most shells already carry on `PATH`, so
`install.sh` only prints a hint. Windows has no equivalent convention, so a
hint-only installer would leave every user with a command they cannot run. The
change is user-scope, additive, announced in the installer output, and
reversible.

Installer step labels are English on Windows even when `OMH_LANG` is set.
`OMH_LANG` is still validated and still forwarded to `omh setup` as
`--language`, so the localized surface that carries real content stays
localized. `install.ps1` is kept pure ASCII because Windows PowerShell 5.1
decodes a BOM-less script as the system ANSI code page and would render
localized labels as mojibake.

### Which config home OMH targets

`~/.hermes` and `~/.omh` are expanded by Python, and Python's
`ntpath.expanduser` resolves `~` from `%USERPROFILE%` — it **ignores `HOME`** on
native Windows:

| Environment | Hermes home | OMH home |
| --- | --- | --- |
| Native Windows | `C:\Users\<you>\.hermes` | `C:\Users\<you>\.omh` |
| WSL | `/home/<you>/.hermes` | `/home/<you>/.omh` |

These are two separate stores on two separate filesystems. Installing under WSL
does not give native Windows Hermes an OMH pack, and vice versa. Setting `HOME`
in a PowerShell profile — a common carryover habit from WSL — has no effect on
where OMH looks; use `HERMES_HOME` and `OMH_HOME` to override, which are honored
identically on every platform.

To see which store a given shell is actually talking to, `omh doctor` prints the
config file it checked as `hermes_config: <hermes home>\config.yaml`. Operators
who want the home on its own line can use the agent-facing `omh probe`, which
reports `Hermes home:` directly.

### POSIX-only surfaces

No skill is POSIX-only. Every skill in the catalog is guidance plus `omh`
commands, which behave identically in PowerShell and in `sh`.

What is POSIX-only is a set of storage and locking primitives. These surfaces
**fail closed** — they refuse rather than weaken their guarantee — because they
exist to make a safety claim that Windows cannot back:

| Surface | Requires | On Windows |
| --- | --- | --- |
| Domain intelligence store (`omh memory domain-status`, `domain-capture`, …) | `O_NOFOLLOW`, `O_DIRECTORY`, dirfd opens, `fcntl` locks | Refuses with an explicit error |
| Domain context attachment in `omh chat route` | same | Routing works; the expert question is not attached |
| Prompt compatibility audit (`omh ops prompt-compatibility-audit`) | dirfd-anchored traversal | Refuses to read prompt sources |
| Plugin static risk audit (`omh ops plugin-risk-audit`) | dirfd-anchored traversal | Refuses to scan plugin source |
| Cross-harness benchmark sandbox | Linux `bwrap` process confinement | Reports `unsupported`; no real runs |
| `0600` / `0700` artifact permissions | POSIX mode bits | `chmod` is close to a no-op on NTFS; private artifacts are not enforced private |
| macOS menu bar helper | Darwin + `swiftc` | Skipped, and says so |

Generic record locking is **not** on that list: `local_store` uses
`msvcrt.locking` on Windows, so shared-record updates get a real OS lock with
the same guarantees as POSIX. See
[Architecture](ARCHITECTURE.md) for the locking model.

## What Setup Changes

OMH's setup footprint is intentionally bounded:

- It installs managed Hermes-visible skills and records local status contracts.
- It can repair or reapply managed `skills.external_dirs` when a Hermes
  profile drifts.
- It applies the same managed registration to every Hermes bot profile —
  each an independent home under `~/.hermes/profiles/<name>` — so Desktop bot
  chats see the same OMH skills as the default chat. See
  [Bot Profiles](#bot-profiles).
- It enables the managed `omh` plugin and selects the OMH memory provider only
  when the corresponding provider slot is free. Existing foreign ownership is
  preserved.
- It defaults `display.interface: tui` whenever the user has not chosen an
  interface — on fresh configs and on existing configs alike, so upgraders
  reach the installed HUD without knowing about `hermes --tui`.
- Interactive `omh setup` and `omh update` offer a default-Yes branded-TUI
  choice when the canonical config is not already
  `display.interface: tui` plus `display.skin: omh`. Accepting it (or passing
  `--yes`) sets both values, so bare `omh` and `hermes` open the same
  OH-MY-HERMES TUI. An already-active update does not ask. No or
  `--no-omh-tui` preserves the current values. JSON suppresses prompting;
  explicit canonical values remain unchanged unless `--yes` supplies consent.
  Dry-run never persists a previewed change. Noncanonical/quoted YAML shapes
  never prompt or change, even with `--yes`. Uninstall does not remove an
  accepted display selection.
- It adds `auxiliary.compression.fallback_chain` when the config pins
  compression to a single provider and already lists other fallback providers.
  Without a compression fallback, one unreachable endpoint leaves a session
  unable to compress and unable to fall back — an unrecoverable
  `Cannot compress further` loop. The chain is derived only from providers the
  user already configured; an existing user-authored `fallback_chain` is never
  overwritten, and no endpoint is invented. See `examples/hermes-config.yaml`.
- It keeps CLI output available for setup, doctor, update, and wrapper
  backends.
- It does not patch Hermes core, run hidden coding work, or turn a prepared
  handoff into observed execution.

The top-level `changed` value in `omh setup --json` is an aggregate: it is true
when any managed setup field changes, including skill registration, compression
fallbacks, plugin enablement, the fresh-config TUI default, or memory-provider
selection. Model-alias writes remain a separate preview-and-approval step.

## Bot Profiles

Hermes bot profiles (`hermes profile create`, Desktop bot chats) are fully
independent Hermes homes under `~/.hermes/profiles/<name>` — each with its own
`config.yaml`, skills resolution, and plugin directory. A registration written
only to the primary home never reaches them, which is why a bot chat can show
zero OMH skills while the default chat has the full set.

`omh setup` and `omh update` sync every profile automatically:

- an already-registered profile is refreshed to the running version;
- a profile with no OMH bundle at all — including a bot created after
  install — gets the full bootstrap on the next `omh setup` or `omh update`;
- a deliberately unregistered profile (see below) is left alone.

`omh uninstall` is symmetric with the sync. A full uninstall (`omh uninstall`,
`--all`, or `--purge`) clears every profile's registration and removes its
managed artifacts — the plugin bundle, the TUI widget, and the skin — through
the same manifest checks the primary home gets: a profile directory OMH cannot
prove it owns is kept and reported, never deleted blind. `--registration-only`
unregisters every profile while keeping their plugin directories, which is
exactly the deliberate opt-out state described below.

After a sync, restart Hermes Desktop so bot chats reload their skills.

To keep OMH out of one bot, unregister that profile only:

```sh
omh --hermes-home ~/.hermes/profiles/<name> uninstall --registration-only
```

The plugin directory stays in place as the opt-out marker; setup and update
never re-register a profile in that state.

OMH workflows are skill triggers, not Hermes slash commands, so they do not
appear in the `/` autocomplete — in any chat, bot or default. Invoke them as
`$ulw …`, `$plan …`, `$research …` (or plain phrasings like `ulw work …`),
and list what is installed with `/skills`.

The curl installer intentionally stops before setup. It installs the isolated
command package and `omh` executable only. `omh setup` is the explicit,
repairable step that installs generated managed skills and registers them with
Hermes through `skills.external_dirs`.
When `omh setup` is run in a real terminal, it asks exactly one question —
install scope (user or project). Output is English by default (`--language`
or `OMH_LANG` opt into ko/ja/zh), Hermes registration
defaults to on (`--skip-apply` opts out), and there is no upfront coding-agent
question: Hermes asks who should own coding work at the first coding request,
in natural language. Optional surfaces stay behind flags — `--with-mcp` for
the tool bridge, `--with-menubar`/`--no-menubar` for the menu bar, `--star`
to star the GitHub repo. Team/profile packs and operating models stay
available as explicit commands or flags, but setup does not make a user lock
the whole organization shape during first install. In non-interactive shells
it uses the same safe defaults and
prints a concise step-by-step summary. Use
`omh setup --json` or `OMH_OUTPUT=json omh setup` for the full
machine-readable payload.

Setup also records OMH project-memory policy in `.omh/setup-profile.json`.
The default is safe `review-first` memory: OMH can capture local candidates,
but reviewed records are required before recall enters coding handoffs. Operators
can choose:

```sh
omh setup --memory-mode off
omh setup --memory-mode review-first
omh setup --memory-mode auto-safe
```

`auto-safe` approves only locally safe summaries and leaves credentials, raw
logs, full transcripts, short-lived PR/commit IDs, and temporary task progress
for review or rejection. This is OMH project memory under `.omh/memory/`; setup
does not mutate Hermes global or internal memory.

The default user scope writes `~/.omh` and `~/.hermes`. Use project scope when
one repository needs isolated local OMH skills and Hermes config:

```sh
omh setup --scope project
omh --scope project doctor
```

The installer also prints the installed `omh` command path. By default it uses
an isolated OMH virtual environment and links `omh` into a user bin directory
when possible. If that directory is not on `PATH`, add the printed directory to
`PATH` or run the printed absolute `omh` path directly. `omh doctor` includes a
non-blocking command availability warning for this case, so source checkouts,
wrapper runtimes, and absolute-path installs can still verify Hermes
registration without pretending the shell alias is ready.

Plugin support is installed by `omh setup` by default. It provides a thin
Hermes plugin bridge in addition to the skill pack:

That installs `~/.hermes/plugins/omh` with deterministic workflow
recommendation, metadata-only HUD/status/role support, and a bounded evidence
probe.
`omh hud` prints the same compact status line a Hermes TUI or plugin surface can
render. It shows only operationally useful status: OMH version, plugin
readiness, target topology, the coding-agent segment described below, and
evidence state. Skill counts, setup inventory, token metadata, and deep
diagnostics are left to `omh doctor`, `omh_status`, and machine-readable HUD
JSON.

The HUD payload also carries a metadata-only plan todo list. When a todo is
declared — by Hermes through the `omh_todo` plugin tool, or by an agent or
operator through `omh runtime todo set` — the modern Hermes TUI
(`hermes --tui`) renders it as a compact checklist below the prompt input,
after the status and activity rows. The classic Python TUI does not load TUI
widget files, so this panel is a modern-TUI-only surface.
`omh runtime todo show` prints the todo projection the HUD payload carries
(`todo` plus `display.todo_lines`), and `omh runtime todo clear` removes it. Todo items are plan declarations, never execution, review, CI, or
merge evidence; an all-done list collapses to a single header line and a list
untouched for 24 hours is hidden as stale.

#### Status model: no-run, prepared-handoff, observed-run

`omh setup` deliberately records a safety-first `choose` preference and asks
no upfront coding-owner question, so Hermes asks which coding agent to use at
the first coding request instead of at install time. The HUD line and the
coding metadata retained by the `menubar_status/v2` payload follow the same
three-state model so that an unselected coding agent never reads as an idle
external agent named `choose`/`ask`:

1. **No-run.** No coding request has been routed yet.
   - No preference recorded (the normal safety-first default): the HUD
     `coding-agent` segment is executor-neutral,
     `coding-agent:not-selected`, and the menu bar payload's
     `settings.coding_handoff` reads `Coding agent: Not selected` with
     `source: "none"`. The menu ends with a compact `coding` metadata footer
     rather than presenting this as an observed run.
   - A real preference was recorded (for example `omh setup
     --default-executor codex`): the executor name is shown because it is a
     genuine user choice, not a placeholder — `coding-agent:idle(codex)` on
     the HUD line, and `Coding agent: Codex` with `source: "user_preference"`
     in the menu bar payload.
2. **Prepared handoff.** `omh coding delegate --record` prepared a handoff for
   a run but execution has not been observed: `coding-agent:prepared(codex)`
   on the HUD line, and the menu bar payload records
   `source: "prepared_handoff"`.
3. **Observed run.** A run recorded observed evidence (dispatch, execution,
   verification, review, CI, or merge): the HUD line shows the run's actual
   phase, for example `coding-agent:runtime(codex)`, and the menu bar payload
   records `source: "observed_runtime"`. The `evidence` HUD segment keeps the
   same prepared-versus-observed boundary as before.

A quiet no-run line looks like
`[omh] v1.0.6 | plugin:ready | target:single | coding-agent:not-selected`.
The plugin also exposes `omh_context` for a compact OMH mental model plus
generic-tool checkpoint, `omh_memory` for a metadata-only comparison of Hermes
memory against OMH's approved records, `omh_interact` for shell-free chat responses and
metadata-only wrapper session records, `omh_recommend` for route hints without
session recording, `omh_probe` for local setup/runtime status and
capability-roadmap cards, `omh_role`, validates `[omh-role:name]` markers for
delegated subagent prompts, and records a metadata-only session-end checkpoint
when OMH runtime state exists. It also exposes `omh_gather_evidence` for
explicit allowlisted local verification probes such as OMH doctor, harness
validation, docs checks, unittest, compileall, and whitespace checks. It does
not provide an arbitrary shell, patch Hermes core, dispatch executors, prove
execution, or prove Hermes has loaded it. Wrapper session records include
`record_provenance` so plugin-authored metadata and wrapper/backend metadata
remain distinguishable.
If the target Hermes runtime requires a separate plugin enable command, follow
that runtime's plugin enable/reload step.

For a quick terminal check of the native menu bar/status-widget surface, use the
human-readable summary:

```sh
omh menubar status
```

It prints Summary, Sessions, Models, the compact coding metadata footer, and
Observation sections instead of a raw JSON blob. For native menu bar,
status-widget, wrapper, or automation integrations, use the platform-neutral
view model:

```sh
omh menubar status --json
```

The `menubar_status/v2` JSON retains the separate `hermes_agents` and
`external_coding_executors` metadata and adds read-only Hermes process, session,
and model observations. Its `display.menu_cards` contains Sessions and Models
tables followed by one compact `coding` metadata footer. The Sessions columns
are exactly `Hermes session` / `Count`, and its rows are only `live` and
`total`; source or TUI breakdown is intentionally not shown. Session counts
come from a read-only read of Hermes' own session store. In Models, `current`
is the model observed on the live Hermes session, while `main` and any auxiliary
alias rows are settings read from Hermes configuration. A configured model is
not evidence that a request used it. The `settings.coding_handoff.source` field
continues to distinguish `"none"`, `"user_preference"`,
`"prepared_handoff"`, and `"observed_runtime"` per the status model above.

On macOS, a normal user-scope `omh setup` also attempts to build and start the
small OMH menu bar helper when `swiftc` is available. The helper lives under
`~/.omh/menubar`, is started with a user LaunchAgent, and refreshes the same
`omh menubar status --observe-local-processes --json` payload. The visible menu is
grouped as Sessions and Models tables with a compact coding metadata footer
instead of a raw text list. The helper explicitly requests the bounded local
process scan so its header can show observed Hermes agent/process counts; plain
`omh menubar status` does not scan processes unless
`--observe-local-processes` is supplied. Use explicit commands when you want to
manage it yourself:

```sh
omh menubar install
omh menubar start
omh menubar stop
omh menubar uninstall
```

Set `OMH_MENUBAR=0` or run `omh setup --no-menubar` to skip the helper. Run
`omh setup --with-menubar` to request it explicitly. Missing `swiftc` or a
failed helper start does not make the OMH workflow setup fail; setup reports the
menu bar step separately.

A native macOS MenuBarExtra app, the OMH menu bar helper, or a test harness can
pass a short-lived `menubar_process_overlay/v1` file, or ask the backend to do a
bounded local process observation, when it has actually observed local process
state:

```sh
omh menubar status --overlay /path/to/overlay.json
omh menubar status --observe-local-processes
```

The overlay and local observation are app-local and expire by TTL. OMH does not
infer that a prepared coding-agent action was executed, reviewed, passed CI, or
merged. The session-store and configuration observers are local and read-only:
the status path makes no network request and does not write Hermes-owned files.

MCP bridge setup is also optional and intentionally conservative:

```sh
omh setup --with-mcp
omh setup --with-mcp --mcp-host codex
omh setup --with-mcp --mcp-host claude-code
omh mcp manifest
omh mcp config-recipe --host claude-code
omh mcp config-recipe --host codex
omh mcp config-recipe --host opencode
omh mcp config-recipe --host cursor
# wrapper/host adapters can record observed host load when they see it:
omh mcp observe-host --host hermes-agent --session <session-id> --event host_load --evidence-ref <host-log-ref>
```

`omh setup --with-mcp` records `mcp_mode: bridge_requested` in setup state and
keeps `observed: false` until a Hermes/MCP host records a concrete load or
tool-call event. Add `--mcp-host codex`, `--mcp-host claude-code`,
`--mcp-host opencode`, or `--mcp-host cursor` when you want setup to write the
local host config entry for the OMH stdio server. Use `--mcp-config-path` when
the host config lives somewhere non-standard, and `--mcp-command` when the host
needs an absolute installed `omh` command path.

`omh mcp manifest` prints the generic stdio MCP bridge contract, and
`omh mcp config-recipe --host ...` prints host-shaped copy-paste snippets for
common MCP-capable environments. Config text written by setup or printed by a
recipe is still only host-config evidence, not host-runtime evidence. The bridge
exposes only local `omh_status`,
`omh_recommend`, and `omh_probe` tools; it is not arbitrary shell access,
connector execution, coding dispatch, or proof that an MCP runtime is active.
`omh mcp observe-host` is for host/wrapper adapters that already observed
bridge load or use and can attach a stable evidence reference. It records
`omh_mcp_host_session/v1` metadata; it does not discover or force host loading.

The OMH plugin follows the same evidence split. `omh setup` installs the plugin
bundle and `omh doctor` can prove local import/register smoke. A Hermes host or
wrapper that actually sees the plugin load can record that runtime event:

```sh
omh plugin observe-host --host hermes-agent --session <session-id> --event plugin_load --evidence-ref <host-log-ref>
omh plugin observations
```

This writes `omh_plugin_host_observation/v1`. It is plugin load/use evidence
only; it is not coding dispatch, implementation, review, CI, merge, or proof of
unrecorded plugin calls. Observed `plugin_load`, `tool_call`, `hook_call`, or
`status_query` records count as active runtime observations. Observed
`session_end` or `plugin_unload` records are historical runtime evidence only.
`blocked` means the host or wrapper could not inspect the plugin state; it does
not preserve an older active-ready claim.

When the managed plugin is actually invoked, hosts can also pass bounded
`observation` metadata to OMH plugin tools/hooks. The plugin then records the
same `omh_plugin_host_observation/v1` event automatically, without storing raw
prompts or tool bodies. This proves only the recorded plugin tool/hook use.

## Install Path A: Hermes-Native Skill Tap

Use this path when the target Hermes environment supports skill taps:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

Use the full identifier for first install. It avoids short-name resolver
ambiguity in current Hermes CLI releases while installing the same
`oh-my-hermes` skill.

Install additional workflow skills when you want direct Hermes skill surfaces:

```sh
hermes skills install ulw-interview
hermes skills install ulw-plan
hermes skills install ulw-research
hermes skills install omh-code-review
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

The installer path has a separate first-time downloader smoke. Plan mode is
also safe for CI and only describes the isolated HOME, venv, bin directory,
command-install and installed-command checks:

```sh
omh release install-smoke
```

When you want observed evidence that `install.sh` itself works from a checkout,
run it live. This still does not mutate your real Hermes profile; OMH creates a
temporary HOME, virtual environment, and bin directory, then runs
`install.sh` and installed-command smoke inside that isolated target. It does
not run setup or doctor unless an advanced one-shot compatibility smoke opts in
with `--run-setup`:

```sh
omh release install-smoke --live --repo-root "$PWD" --install-script "$PWD/install.sh"
```

The plan also reports `installed_command_smoke` and
`first_use_status_smoke`. The first checks that the installed `omh` command is
discoverable on PATH before proving the console script can run; the second locks
the first Hermes chat/status boundary so pre-handoff status does not show
executor open/result actions.

After installing OMH into the target runtime, verify the command path too:

```sh
command -v omh
omh --help
omh release skill-content-smoke --json
omh release product-readiness --version 1.0.5 --json
omh release evidence-bundle --version 1.0.5 --write --json
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --install-path setup --omh-command omh --include-command-smoke
```

`release skill-content-smoke` checks the installed command package's generated
skill guidance, including router awareness and workflow context rails. It also
checks bundled role context, all-skill awareness lane coverage, full capability
manifest context, playbook capability context, standalone plugin capability
fallback coverage, fallback routing/context/boundary fields, bounded prompt
context budgets, and bounded capability payload budgets.
In short, it preserves bounded context budgets while still giving Hermes enough
OMH workflow context to route well.
It is not Hermes chat-load evidence. When an operator explicitly wants live
evidence from the target Hermes profile, run one of these:

Use `omh release product-readiness --version 1.0.5 --json` when you want a
single release-candidate card that combines skill content, G1-G10 use-case
readiness, parity contracts, and release checklist shape. It is still local
contract evidence, not live Hermes chat or executor evidence.

Use `omh release evidence-bundle --version 1.0.5 --write --json` when you want
that local release-candidate evidence written under
`.omh/runtime/release-evidence/` for a release PR or release note. The bundle is
not CI, live Hermes smoke, executor, delivery, merge, or GitHub release evidence.

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup
```

The live smoke runs the selected install path and then verifies:

```sh
hermes skills tap list
hermes skills list --enabled-only
hermes skills check oh-my-hermes
hermes skills inspect rlaope/oh-my-hermes/skills/omh-routing
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
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

By default this installs the `stable` channel: the newest published release,
as a wheel. To pin a specific release instead, pass its version — the channel
is already the default, so naming it is optional but harmless:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

To track the unreleased `main` branch instead, ask for `preview` explicitly:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_CHANNEL=preview sh
```

The two channels download different artifacts, and the difference is large
enough to plan around:

| Channel | Artifact | Measured size | Measured time |
| --- | --- | --- | --- |
| `stable` (default) | `oh_my_hermes-<version>-py3-none-any.whl` release asset | 2,714,885 bytes at v1.0.6 | 0.55s |
| `preview` | `main` branch repository archive | 46,012,605 bytes on 2026-08-15 | 5.71s |

Sizes and times measured 2026-08-15 with `curl`. Two things make the gap
bigger than the byte ratio suggests. The preview archive is the whole
repository, including `assets/`, `tests/`, and `site/`, none of which is
needed to run `omh`. And GitHub *generates* `archive/refs/heads/<branch>.zip`
on demand for every request rather than serving a cached object, so preview
pays generation latency each time — on an ordinary connection that download
has been observed to take over five minutes. Release assets are static objects
served from a CDN.

Preview stays an archive because GitHub publishes release assets per tag and
there is no per-branch wheel to point at. Use it only when you specifically
need unreleased `main`.

A version-less `stable` install asks GitHub which release is newest by reading
a single redirect (`releases/latest`), which costs about 0.25s. If that lookup
fails, the installer says so and tells you to pass `OMH_VERSION` or switch to
`OMH_CHANNEL=preview`; it never guesses a URL. The installer does this lookup
itself and passes the resolved version to `omh setup`, because `omh` makes no
network calls of its own.

> **`omh update` still defaults to `preview`.** Only the installer default
> moved. Until the release-version lookup has a home inside `omh` that does not
> break its no-network boundary, a plain `omh update` keeps fetching the branch
> archive. To get the slim path from `omh update` today, name the release:
> `omh update --channel stable --version <version>`.

Releases published before the wheel-publishing workflow existed carry no
asset. If a stable install reports a 404 for the wheel, install that tag from
the repository archive instead:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_PACKAGE_URL=https://github.com/rlaope/oh-my-hermes/archive/refs/tags/v<version>.zip sh
```

For custom release archives or local package sources accepted by `pip`, pass
`OMH_PACKAGE_URL`. To install from a fork or mirror, override
`OMH_REPO_ASSET_ROOT` and `OMH_REPO_ARCHIVE_ROOT`.

The installer creates an isolated OMH virtual environment and links the `omh`
command into `~/.local/bin` when possible. It does not run `omh setup`, register
Hermes skill directories, install plugin state, or run `omh doctor` by default.
That avoids Homebrew and distro Python `externally-managed-environment`
failures while keeping the setup boundary visible: install the command first,
then run `omh setup` when you are ready to connect OMH to Hermes.

Installer and setup output can be localized with `OMH_LANG` or `--language`.
Supported language codes are `en`, `ko`, `ja`, and `zh`:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_LANG=ko sh
omh setup --language ko
```

Installer localization is separate from routing localization. Backend routing
surfaces such as `omh recommend`, `omh playbook recommend`, and
`omh chat interact` use a deterministic local phrase layer for tested Japanese,
Chinese, Korean, Spanish, French, German, and Hindi operator-routing requests. The layer expands known
phrases into canonical routing signals, includes `locale:<code>:<label>` in the
matched evidence for scored recommendations, and never calls external
translation services. Renderable chat cards also use a small local copy catalog
for common English, Korean, Japanese, Chinese, Spanish, French, and German
operator-facing frames such as the skill picker, source finder, paper learning,
web research, image summary, and workflow-learning missed-route cards. If a
phrase or card locale is not covered, OMH falls back to the normal English
clarify or planning path instead of pretending to translate.

From the user's point of view, the intended final state matches the Hermes tap
path: Hermes can discover OMH skills and the user talks to Hermes. `omh setup`
is the bootstrap/maintenance route that produces that state through generated
skills and `skills.external_dirs`.

After it finishes, restart Hermes Agent or the hosted wrapper so it can reload
the registered skill directory.

## Set Up And Verify

Run setup explicitly after the installer, and re-run it whenever you want to
repair or refresh the local Hermes skill registration:

```sh
omh setup
omh doctor
```

The following are agent, wrapper, or operator diagnostics. Normal users do not
need to run them as part of setup:

```sh
omh list
omh runtime status
omh runtime team-readiness
omh probe
omh probe --parity
omh probe --roadmap
```

`omh setup` should report a human-readable setup summary by default, including
the setup location, overall readiness, terminal command availability, OMH
workflow path, Hermes connection path, coding request preference, profile
check, and OMH status helper state. It should not require first-time users to
understand internal config keys, topology names, MCP state, state-log entries,
or plugin manifests. In a real terminal it first asks for setup language, then
only asks for a simple coding-agent suggestion plus optional tool bridge
settings when advanced setup is explicitly opened. The same command with `--json` should include install and apply
steps, an `operator_summary` block, and a `hermes_native_setup/v1` block that
names the equivalent Hermes skill install path, managed skill directory, and
`skills.external_dirs` registration key.
`hermes_native.observed` means the local bootstrap/apply step actually ran; it
does not prove Hermes has reloaded or used the skill yet.
`discovery_status: config_registered_reload_required` means restart or refresh
Hermes before claiming the skill is visible in chat.
`omh doctor` should report a grouped health summary by default: managed skills,
runtime state, Hermes registration, target topology, optional surfaces, command
availability, issue counts, recommended next action, and the `last_doctor`
state-log entry when the runtime directory is writable. `omh doctor --json`
returns the full check payload plus `doctor_summary/v1`. `omh list` should show
a concise managed skill summary plus workflow lanes by default. `omh list
--json` returns the managed manifest plus `omh_installed_skill_catalog_context/v1`
and per-skill descriptions, routing hints, examples, and evidence boundaries.
The human-default commands are `omh setup`, `omh update`, and `omh doctor`.
Several maintenance and catalog commands also print readable terminal summaries
for advanced operators: `omh install`, `omh uninstall`, `omh apply`, `omh
list`, `omh recommend`, `omh playbook ...`, `omh profile ...`, `omh probe`, and
`omh snippet --output`. Readable output does not make them normal user workflow.
Use `--json` on those commands, or set `OMH_OUTPUT=json`, when a wrapper or
automation needs the complete payload.
Plain chat preview commands such as `omh chat route`, `omh chat route-hint`, and
`omh chat interact` are also summary-first for terminal users. Use `--json` on
those commands when an adapter needs `chat_route_hint/v1`,
`chat_interaction/v1`, or another complete machine-readable envelope.
Short chat requests such as `omh update`, `omh setup`, `omh doctor`, `omh
install`, and `omh list` should stay in that maintenance lane: run the requested
command, summarize observed output, and avoid repo changes unless the user asks
for code work separately.
Agent and wrapper ledger/control-plane commands such as `omh chat session`, `omh coding`,
`omh runtime`, `omh goal`, `omh loop`, `omh memory`, `omh state`,
`omh harness`, `omh release`, and `omh demo` print JSON by design because they
are wrapper contracts rather than the normal human chat surface.
`omh runtime status` should show the local runtime artifact directory and the
latest install/apply/doctor state when those commands have run. `omh probe`
reports observable Hermes capability surfaces without mutating Hermes internals.
For MCP, `omh probe` reports the bridge server, setup preference, runtime tool
call observation, host session observation, and host config separately:
`mcp_preference` means `omh setup --with-mcp` was requested in OMH local state,
`mcp_bridge_server` means the installed command package exposes `omh mcp serve`,
`mcp_bridge_runtime` means OMH has observed a local MCP bridge tool call, and
`mcp_host_session` means a host or wrapper recorded load/session evidence with
`omh mcp observe-host`. `mcp_host_config` means OMH can currently find a
supported local host config entry for the OMH stdio bridge, such as Codex TOML,
Claude Code JSON, OpenCode JSON, Cursor JSON, or another recipe-compatible
config file. `omh mcp config-recipe --host
claude-code|codex|opencode|cursor|generic` can prepare the matching config
shape, but a written or pasted config entry is still not runtime evidence.
These fields do not prove connector invocation, coding dispatch,
implementation, review, CI, merge, or unrecorded host-specific MCP load unless
separate runtime evidence records that event.
After `omh setup` has run, `omh doctor` also checks the managed plugin manifest
plus local import/register smoke. `omh probe` reports
`plugin_distribution_ready` separately from `native_integration_claim_ready` so
operators do not mistake local install readiness for observed Hermes runtime
use. When a host or wrapper records `omh plugin observe-host`, or invokes an OMH
plugin tool/hook with bounded `observation` metadata, `plugin_runtime_observed`
can become available. `native_integration_claim_ready` can become true only when
the latest observed plugin event is active (`plugin_load`, `tool_call`,
`hook_call`, or `status_query`); observed `session_end` and `plugin_unload`
remain historical evidence only.
Use `omh runtime team-readiness` when an operator or wrapper wants to know
whether Hermes/team/swarm coding paths are ready to present. It returns
`omh_team_worker_readiness/v1` with the installed skill visibility, runtime
templates, wrapper actions, worker ACK/result requirements, and current
`runtime_observation/v1` status. If no worker event has been recorded, it should
still say `not_observed`; readiness is not worker execution. The payload keeps
`contract_status` separate from `presentation_status`, so wrappers can tell the
difference between "OMH ships this contract" and "Hermes can currently see the
installed team/ultrawork skill surface."

Use `omh probe --parity` when an operator wants the broader comparison against
common oh-my runtime capability axes. It returns `omh_parity_matrix/v1` with
available rows for skills/plugins, roles, team/swarm workers, worktree
isolation, HUD/session status, MCP/tool bridge, loop autopilot, and release
maintenance. Available means OMH has the deterministic contract or backend
surface for that axis; live runtime actions still need separate observed
evidence. The worktree row includes
`worktree_session_isolation/v1` wrapper guidance when coding handoffs need same
workspace, recommended worktree, or required worktree status before opening a
coding agent. Worktree creation is deferred to native tooling — upstream Hermes
manages worktrees (Kanban worktree-per-task since v0.15.0, Desktop Projects
since v0.18.0) or you run `git worktree add` — and OMH records
`omh_worktree_observation/v1` for the resulting worktree; that still proves
workspace isolation only, not executor dispatch or implementation.

Use `omh probe --roadmap` when the question is "what should I do next?" rather
than "what does OMH support?" It returns
`omh_capability_gap_roadmap/v1` and separates baseline product/setup gaps from
host or wrapper evidence gaps. For example, missing managed skills or Hermes
registration points to `omh setup`; missing plugin runtime, MCP host-session,
or wrapper-session observations points to the host or wrapper evidence that
must be recorded before OMH can claim those runtime states. `omh probe
--parity` includes the same roadmap so a wrapper can render capability parity
and next actions in one status card. Roadmap actions separate executable
backend commands from `operator_instruction` text so chat wrappers can render
human/Hermes guidance without treating it as a shell command.

For concrete examples that show how the installed skills should affect coding,
planning, and specialist review flows, see
[Application Cases](APPLICATION_CASES.md).

The public project site at
`https://rlaope.github.io/oh-my-hermes/` is a short entry point. Treat
this `docs/` directory and the root README as the source of truth for operating
details.

## Chat Wrapper Backend Flow

If Hermes Agent is running behind a Discord bot, Slack app, or hosted chat
adapter, install `oh-my-hermes` on the same machine, container, or runtime
image that starts the wrapper.

The backend flow is:

1. The wrapper receives a user message in Discord, Slack, Telegram, or another chat
   surface.
2. The wrapper calls `omh chat interact` with the platform source and either a
   plain message or event JSON.
3. `omh` returns one `chat_interaction/v1` envelope with a renderable
   `chat_response/v1`, optional `status_card/v1`, a stable `thread_key`,
   platform-neutral actions, and a conservative `next_action`.
4. At startup or deploy time, the wrapper can call
   `omh chat native-command --source discord`, `--source slack`, or
   `--source telegram` to obtain the platform registration contract for `/omh`
   or the equivalent command/menu surface.
5. If the message is a partial command prefix such as `./`, `/`, `./o`, or
   `/om`, the wrapper renders `chat_response.state.command_preview.suggestions`
   as autocomplete when the platform supports it. If native autocomplete is not
   available for plain messages, render the returned
   `omh_command_fallback_card/v1` style card with a single `Open omh` action.
   Selecting it submits `./omh` or `/omh` and opens the workflow picker.
6. If the message is `./omh`, `/omh`, `./skills`, or `/skills`, the wrapper
   renders `chat_response.state.skill_picker.options` as a platform-native
   select menu, button list, or Hermes TUI command list. Selecting an option
   forwards the original request to that skill. This keeps installed skill
   names clean; the skills do not need an `omh-` prefix.
7. If the user asks what OMH commands, skills, or workflows are available, the
   wrapper still renders `chat_response.kind == skill_picker`. Do not ask the
   user to approve `omh list` for a catalog question; `omh_skill_picker/v1`
   already contains the workflow labels, direct invocation text, and
   routing-only claim boundary. The same response also carries
   `omh_capability_summary/v1`, which lets Hermes explain the larger
   capability lanes and representative playbooks without a second catalog
   command.
   When the wrapper needs the compact mental model rather than the full picker,
   it can use `omh context brief --json` or plugin tool `omh_context` to fetch
   `omh_context_brief/v1`: lanes, common cues, generic-tool checkpoint, optional
   route hint, and response rules without storing or echoing the raw prompt.
   If the user asks "what is OMH?" or "how do I use OMH?", `omh chat interact`
   can now return `chat_response.kind == context_brief` directly, with the same
   structured `omh_context_brief/v1` under `chat_response.state.context_brief`.
8. If the user asks what to do next after setup or install, the wrapper returns
   `chat_response.kind == quickstart` with `[omh] quickstart`, the
   `omh_quickstart_card/v1` payload, first-use Hermes prompts, and the same
   capability roadmap metadata. If the user explicitly asks for detailed status,
   the wrapper returns `chat_response.kind == status` with `[omh] status` and
   `chat_response.state.capability_gap_roadmap`. Both paths separate missing
   product setup from missing host/runtime evidence without making the user
   approve shell commands just to understand OMH health.
9. The wrapper renders `chat_response.headline`, `body`, `state`, `actions`, and
   `status_card` when present in the original channel or thread. The headline
   already starts with the visible OMH marker, such as `[omh] research`;
   adapters can read `chat_response.usage_trace` for the selected workflow,
   harness, executor, and evidence boundary without parsing prose.
   `chat_response.state.workflow_explanation` gives the same surface a compact
   why/next/not-evidence card so Hermes can explain why OMH selected this
   workflow, what the user or wrapper should do next, and which claims are
   still not observed evidence.
10. Adapters apply `chat_response.messenger_rendering` for the selected surface:
   Discord, Slack, and Telegram default to `limited_markdown`, while Hermes TUI,
   web, and generic rich Markdown surfaces default to `rich_markdown`. Render
   `chat_response.messenger_rendering.body_text` for that profile. Limited
   profiles convert wide Markdown tables into messenger-safe bullets when
   possible; rich profiles preserve tables. If a rich response is later relayed
   into a narrow chat surface, use
   `chat_response.messenger_rendering.fallback_body_text` or call
   `omh chat interact --render-profile limited_markdown`. The prefix appears
   once per response; repeat it only if the adapter splits a long answer into
   separate posted chunks.
11. If the interaction asks for clarification, the wrapper keeps the answer in
   the same thread and calls `omh chat interact` again with the updated message.
12. If the interaction presents a plan, the wrapper waits for the user to accept
   or revise it before preparing any coding handoff.
13. If the accepted interaction exposes executor or runtime selection, the
   wrapper uses the chosen profile. Codex can use the run-backed lifecycle path;
   Claude Code and generic agents use prompt-only handoffs; Hermes, OMX, OMO,
   and OMC use runtime handoffs with team/swarm, worker-protocol, and worktree
   guidance. The wrapper records only what it actually observes.
14. Before dispatching to a coding profile, the wrapper runs
   `omh coding executor-readiness --executor <profile>` and reads
   `executor_readiness/v1`. OMH reuses its stored observation while that
   observation is still fresh and still bound to the same profile, tool,
   permission profile, and workspace, so the wrapper does not need a cache of
   its own. If the probe reports `missing` or `blocked`, ask the user to choose
   another coding agent, configure PATH, continue in Hermes, or keep a
   prompt/runtime handoff. Retry only after that state changes. If it reports
   `stale`, read `pre_handoff_repair_card/v1` for the missing prerequisite and
   the repair commands, and keep the handoff prepared instead of dispatching.
   Readiness is not dispatch, implementation, review, CI, or merge evidence.
15. If the wrapper observes Hermes target metadata such as `agent_ref`,
   `agent_count`, or `hermes_home`, `chat_interaction/v1` may include
   `target_notice` and `target_topology`. Render the concise notice or
   `apply_target_change` action before treating single-to-multi or
   multi-to-single target changes as persistent setup state. When target
   identity metadata is present, `thread_key` is scoped by that target so two
   Hermes agents in the same channel do not share wrapper session state.
16. If the wrapper has local memory-like context candidates, it can run
   `omh memory inspect` and attach a conflict-free `handoff_context_pack/v1` to
   the later handoff. Conflicting or stale assumptions must be shown as memory
   review, not silently reused.
17. Status updates use `omh coding lifecycle report` or
   `omh chat interact --run <run-id>` and stay in the same thread.
18. Hermes still starts with its normal config and reads `skills.external_dirs`;
   `omh apply` makes sure `~/.omh/skills` is included in that discovery list.

`omh` provides deterministic local contracts for command registration, fallback
cards, workflow selection, handoff, and status. The active Hermes wrapper owns
the transport session, platform registration side effect, and later observed
evidence updates.

For a hosted bot, the practical bootstrap shape is usually:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
omh doctor
```

Then restart the bot process so Hermes reloads its config and skill directory.

Minimal wrapper calls:

```sh
omh chat interact --source discord --json --event-json event.json
omh chat interact --source slack --json "risky refactor"
printf '%s' "$SLACK_TEXT" | omh chat interact --source slack --json --stdin
omh chat interact --source discord "risky refactor"
```

The default terminal output is a compact operator summary. Wrappers and adapters
should pass `--json` when they need the machine-readable
`chat_interaction/v1` envelope. The summary keeps the usual chat actions visible
for operator QA; JSON remains the complete backend contract.

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

Check the selected coding agent before dispatch:

```sh
omh coding executor-readiness --executor codex
omh coding executor-readiness --executor claude-code
omh coding executor-readiness --executor omx-runtime
```

If the result is `missing` or `blocked`, keep the handoff prepared and ask the
operator whether to choose a different coding agent, configure PATH, continue in
Hermes, or use a prompt/runtime handoff. Do not treat this probe as proof that
the coding agent ran.

If the result is `stale`, an earlier observation no longer describes this
machine: it aged past its window, or the profile, tool, permission profile, or
workspace it was bound to changed. The payload names the gap in
`pre_handoff_readiness/v1` and the repair path in
`pre_handoff_repair_card/v1`. Keep the handoff prepared, run the card's
commands, and re-observe readiness explicitly:

```sh
omh coding executor-readiness --executor codex --force
```

Agent and wrapper operators can record a bounded local capability observation
separately when the host has actually exposed it. This is a control-plane
artifact, not a normal user command and not a substitute for executor, review,
CI, or merge evidence:

```sh
cat > capability-observation.json <<'JSON'
{
  "parallel_agents": {
    "status": "host_observed",
    "scope": {"host": "local", "surface": "native_subagents"},
    "evidence_ref": "host-probe:codex-subagents",
    "observed_at": "2026-07-15T00:00:00Z"
  },
  "visual_qa": {"status": "unknown"}
}
JSON

omh coding capability-snapshot record --executor codex --capabilities-json capability-observation.json
omh coding capability-snapshot inspect --executor codex
omh coding capability-snapshot validate --executor codex
```

`executor_capability_snapshot/v1` stores only bounded capability status,
scope, and evidence references under `.omh/coding/executor-capability-snapshots/`.
It does not select an executor, dispatch work, or claim implementation,
verification, review, CI, merge-readiness, or merge happened.

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
omh chat route --source discord --record --json "risky refactor"
omh chat route --source discord "risky refactor"
omh hermes plan --source discord --record "risky refactor with review"
omh hermes plan-accept .hermes/plans/<accepted-plan.md>
omh coding delegate --executor codex --source discord --record --from-plan .hermes/plans/<accepted-plan.md>
omh coding delegate --executor claude-code --source discord --record "risky refactor"
omh runtime delegation-status --run <run-id>
```

`omh chat route` prints an operator-readable lower-level route decision by
default. Adapters should pass `--json` when they need the complete
machine-readable payload.

`omh hermes plan --record` writes a draft `hermes_plan/v1` Markdown artifact
under `.hermes/plans/`. Each plan includes a deterministic `quality_gate` and
`deep_interview` block. Weak planning requests may also write `.hermes/context/`
so Hermes can ask one blocking clarification. Review gates remain
`not_observed` unless the wrapper can prove a separate review happened.

The stdout JSON also includes `wrapper_contract`. Wrappers should use that JSON,
not the Markdown body, to decide the next local action. If
`wrapper_contract.coding_delegate.available` is `true`, the listed
`argv_template` is an adapter contract for preparing a lower-level delegation
after plan acceptance. Use the accepted plan artifact or generated context pack
as the executor context; Discord/channel text is only a summary. If
`coding_delegate.available` is `false`, follow `next_action` and do not dispatch
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
- append-only lifecycle observations in `~/.omh/runtime/journal/events.jsonl`
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
- plugin `omh_interact` returns the same `chat_interaction/v1` envelope and can
  record a metadata-only wrapper session when Hermes supplies host/session
  metadata.
- `omh chat interact --source discord "<message>"` or
  `omh chat interact --source slack "<message>"` returns a
  `chat_interaction/v1` envelope with a renderable `chat_response/v1`.
- The route contains `route_explanation/v1` with the selected workflow, why it
  was selected, the next action, a wrapper-ready `recommended_reply`, a
  `primary_action_label`, a `primary_action_hint`, and a short list of states
  that are not evidence yet. Special OMH intro, quickstart, status, and catalog
  routes refresh this card after they override the base route.
- Common non-English requests should preserve the user's original text while
  routing through deterministic locale hints when a tested phrase matches. For
  example, Japanese or Chinese payment-failure reports route to
  `feedback-triage`, French or Hindi safe-feature requests route to a plan
  surface, and Spanish, French, German, or Hindi issue-to-PR requests route to `github-event-ops`
  without claiming machine translation happened.
- Common non-English card frames should use the local wrapper copy catalog when
  available, while keeping contract terms such as `Route for me`,
  `source-finder plan`, and evidence boundaries visible for adapters.
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
- `omh coding delegate --executor codex --record --from-plan <accepted-plan.md>`
  uses the accepted `hermes_plan/v1` artifact as executor context. Draft plans
  are rejected unless an operator explicitly passes the override flag.
- `omh coding lifecycle start --executor codex --record "<message>"` creates a
  prepared Codex handoff lifecycle without storing the raw prompt body by
  default.
- `omh coding delegate --executor claude-code --record "<message>"` and generic
  profiles return a `coding_prompt_handoff/v1` prompt-only payload without
  creating a lifecycle run.
- `omh coding delegate --executor hermes --record "<message>"` and
  `omx-runtime` / `omo-runtime` / `omc-runtime` return a
  `coding_runtime_handoff/v1` payload with runtime, team/swarm,
  worker-protocol, and worktree guidance without creating a lifecycle run.
- Coding handoffs include `worktree_session_isolation/v1` so wrappers can show
  Prepare worktree before opening an executor when risk or parallelism calls for
  isolation. The plan remains `prepared_not_observed` until a wrapper invokes
  or observes the workspace action. Worktree creation is deferred to native
  Hermes tooling (Kanban worktree-per-task, Desktop Projects) or a manual `git
  worktree add`; once the worktree exists,
  `omh worktree bind --path <worktree> --executor codex --session <session-id>`
  returns the safe wrapper recipe for opening or attaching the selected coding
  agent from that worktree. Linked runtime ladders still require separate
  `runtime_observation/v1` records.
- Executor-choice, runtime-handoff, clarify, fallback, and prompt-only handoffs
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
  `omh coding delegate --executor codex --record --from-plan <accepted-plan.md>`;
  run it only after plan acceptance and pass the accepted artifact or context
  pack, not the original Discord/channel summary, when the wrapper wants a
  run-backed Codex handoff.
- A chat message that strongly names a workflow reaches Hermes with installed
  skill descriptions available after the wrapper dispatches to Hermes.
- `omh runtime record` can create a run and `omh runtime show <run-id>` can read
  it from the same runtime context.
- `omh probe` reports managed skills and external skill directory registration
  as available before any deeper integration claim is made.
- If skills do not appear, run `omh setup`, then `omh doctor`, then restart the
  bot again.

Current limitation: plugin `omh_interact`, `omh chat interact`,
`omh chat route`, `omh coding delegate`, and `omh coding lifecycle` choose
contracts and record local metadata. Hermes Agent and the selected
executor/runtime still provide the actual conversation, execution, GitHub, CI,
and merge evidence that OMH later records.

## Update

Update the installed `omh` command package and then refresh the managed skill
pack:

```sh
omh update
omh doctor
```

Most users should run only `omh update`. Homebrew, Bun, and npm launchers record
their package-manager provenance; the update runs that manager's native
upgrade, re-enters the updated CLI, refreshes the managed skills, and records a
concise update log. The curl and PowerShell installers follow the same sequence
through their managed virtual environment and recorded preview/stable source.
If `omh` is running from a pip, pipx, distro, source checkout, or custom Python
install that OMH cannot safely mutate, the update still refreshes workflows but
prints
`OMH command: not updated (workflows only)` plus the installer command needed to
update the CLI itself. Successful command package updates print a compact line
such as `OMH command: 1.0.1 -> 1.0.4 (updated)` or
`OMH command: main@old -> main@new (updated)` before the workflow summary.

### Package-manager command updates

When Homebrew, Bun, or npm installed the command, `omh update` uses the matching
native command automatically:

| Installed with | Upgrade command |
| --- | --- |
| Homebrew | `brew upgrade rlaope/tap/omh` |
| Bun | `bun update -g --latest oh-my-hermes` |
| npm | `npm update -g oh-my-hermes` |

If the manager update fails, OMH stops before refreshing content and reports the
manager error. Do not run the curl installer over a package-manager
installation; that creates a second independently managed `omh` command.

Advanced operators using installer-managed commands can still pin or test a
different command package with
`omh update --channel stable --version <version>`. Package-manager installs
reject `--version`, `--package-url`, and `--source-ref` rather than silently
installing a different release; use that manager directly for an intentional
CLI rollback. `omh update --channel local --from-skills-dir ./skills` refreshes
workflow content only and does not replace the command package, plugin bundle,
or Hermes registration. These flags are for release validation, fixtures, or
intentional rollback testing. Local modifications block updates unless
`--force` is supplied.

Run `omh doctor` after an update, then restart Hermes Agent. `omh update`
refreshes existing Hermes registration along with the plugin bundle; use
`omh setup` only when doctor reports that first-time setup or a repair is still
needed. Rerun the installer manually only when `omh update` says the command
package was not updated, or when you intentionally want a one-shot reinstall
from a specific source ref. The installer passes command-package update
evidence into OMH so the state log can show version/ref movement such as
`1.0.1 -> 1.0.4` or `main@old -> main@new` when `OMH_SOURCE_REF` is provided:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_SOURCE_REF=main@<sha> sh
```

Successful setup, install, update, and doctor runs record concise state logs
under `~/.omh/runtime/state.json` as `last_setup`, `last_install`,
`last_update`, or `last_doctor`. The logs record operator status, managed skill
count, source metadata, command-package status, and health summaries without
storing raw chat prompts.

## Reapply

If Hermes does not show the installed skills, reapply the config registration:

```sh
omh setup
omh doctor
```

Then restart Hermes Agent.

## Install Options

### Skill Profiles: Core vs Full

`omh setup`, `omh install`, and `omh update` install one of two skill
profiles:

- **`core`** (opt-in via `--core`). Installs the doctor health floor (the router plus the
  `doctor`, `skill`, `cancel`, and `agent-ops-review` operator skills OMH needs
  to describe, diagnose, manage, and stop itself) plus the workflow skills a
  messenger-first user needs for a first chat/plan/status/handoff session
  (`plan` for planning and coding handoff, `gateway-intent-card` for chat
  delivery/status-update policy, `executor-runtime-readiness` for handoff
  readiness, and `ops-observability-card` for status questions). Everything
  else in the catalog stays opt-in.
- **`full` (default).** Installs every packaged skill, ULW engines included.
  This is what a plain `omh setup` does; `--full` remains for upgrading an
  install that previously chose core and for script compatibility:

```sh
omh setup            # full catalog
omh setup --core     # lightweight footprint instead
omh update --full    # widen an existing core install
```

Every skill OMH installs is skill guidance that Hermes carries into its
routing context on every turn, not just when that workflow is used. A `core`
install keeps that per-turn context weight bounded to the essentials; a `full`
install trades that weight for having every workflow's guidance available
immediately, with no `full` -> `core` skill left unpresented. Choose `full`
when a workspace already knows it will use the wider catalog (specialist
review, research, or ops workflows beyond the messenger-first core); otherwise
`core` is the smaller, faster default.

Machine-readable install output makes this checkable: `install_skill_pack`
always records `skill_profile` (`"core"` or `"full"`) in the install/setup
result and in `~/.omh/manifest.json`, and a `full` install additionally
includes a `context_cost_warning` (`omh_skill_profile_context_cost_warning/v1`)
with the installed skill count, the core-profile skill count, and the extra
skill count so a wrapper or CI check can flag an unintentional `full` install
without parsing prose:

```sh
omh install --full --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["context_cost_warning"])'
```

The warning reports skill *counts*. To see the actual bytes behind them, run
the context-cost report, which measures the always-loaded `SKILL.md` body for
both profiles and shows how much of it is text repeated verbatim across skills
rather than guidance specific to one workflow:

```sh
omh docs skill-context-cost          # human-readable table
omh docs skill-context-cost --json   # omh_skill_context_cost/v1
```

Repetition is derived, not hand-classified: for each `##` heading the report
counts occurrences, distinct bodies, and the duplicate bytes an install pays
for the second and later copies. Policy shared by every generated workflow
skill lives once in `skills/omh-routing/references/skill-common-rail.md`
(progressive disclosure, loaded on demand) rather than inside each body; that
reference ships with the always-installed `oh-my-hermes` skill, so both
profiles resolve it. Reference bytes are reported separately from the
always-loaded total because they are not carried on every turn.

A `core` install still passes `omh doctor` because the core profile installs
a superset of the doctor health-floor skills.

### Reconciling An Existing Full Install Back To Core

`omh setup`, `omh install`, and `omh update` are non-destructive: they never
delete an installed skill directory, so reinstalling with the default `core`
profile after a `--full` install leaves every full-only skill on disk. The
recorded profile then says `core` while the effective per-turn context weight
is still that of a `full` install.

Two commands make that gap visible and fixable:

```sh
omh skill-profile status                          # read-only; mutates nothing
omh skill-profile reconcile --to core --dry-run   # preview the removals
omh skill-profile reconcile --to core             # apply
```

`omh skill-profile status` reports the requested profile (what the last
install recorded), the effective profile (what is actually on disk), the
installed/core/full skill counts, and the skills that would be reconciled.
`omh skill-profile reconcile` is the only OMH path that deletes managed skill
directories, and it never runs as part of setup, install, or update.

Reconcile removes a skill only when it is both **OMH-managed** (recorded in
`~/.omh/manifest.json`) and **unmodified** (every file under the skill
directory is byte-identical to the rendered catalog templates, with no extra
or missing files). Everything else stays on disk and is reported as a
retained exception with its reason:

- `locally modified vs. the rendered catalog templates` for an edited skill.
- `not an OMH catalog skill` for a directory OMH does not ship.
- `no OMH install-manifest record; not OMH-managed` for an unmanaged copy.
- `skill directory is not plainly readable managed content` for symlinked or
  unreadable directories.

Because retained exceptions can survive a reconcile, the manifest records a
`skill_profile_state` block (`omh_skill_profile_state/v1`) on every install
and reconcile so status output is not misleading:

| Field | Meaning |
| --- | --- |
| `requested_profile` | The profile the last install/reconcile recorded. |
| `effective_profile` | `core`, `full`, `mixed`, or `none`, derived from disk. |
| `matches_requested_profile` | Whether the two agree. |
| `full_only_installed_skills` | Full-only skills still installed. |
| `retained_exception` | `true` when `core` was requested but full-only skills remain. |
| `next_action` | The reconcile command to run, or empty. |

```sh
omh skill-profile status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["profile_state"])'
```

A `core` reconcile keeps the doctor health floor, so `omh doctor` still passes
afterwards. Restart or reload Hermes Agent so it picks up the smaller skill
set.

### Hermes Setup Guide Skills (Full Profile)

A `full` install adds four conversational setup guides. Each one is a Hermes
chat skill, not a new CLI command: the normal way to use them is to describe
the outcome in chat and let Hermes run the guide.

| Audience | Chat intent | What the guide covers |
| --- | --- | --- |
| Person using Hermes | Ask Hermes to set up your models. | Walks through the main / realtime-search / design model role slots, provider connection, and session model switching. |
| Person using Hermes | Ask Hermes to make web search cheaper. | Walks through the scraper API key and an auxiliary web-extract model as two separate reviewed diffs. |
| Person using Hermes | Ask Hermes to connect mail and calendar for a morning brief. | Walks through read/draft-only mail and calendar access for an on-demand morning brief. Mail Send permission is never enabled, and any token pasted by the user is never stored. |
| Person using Hermes | Ask Hermes to check it is up to date. | Reports whether the installed Hermes/parallel-tools version is current and, if not, the update command to run. |

Every guide follows the same five-step contract: check prerequisites (marking
unmet ones "not applicable" and skipping them), read a config file or version
read-only, walk the person through any manual step they must perform
themselves (such as OAuth or token issuance), show a diff and apply it only
after explicit approval, then re-verify. These skills install with the `full`
profile; they are not part of the `core` default.

Record the optional MCP bridge preference during setup:

```sh
omh setup --with-mcp
omh mcp manifest
omh mcp config-recipe --host codex
```

Use project-local OMH/Hermes paths during setup:

```sh
omh setup --scope project
```

Install one or more optional Hermes agent/profile packs explicitly when a
wrapper or team wants visible Hermes role files in addition to the generated
skill workflows. These packs are never installed by default and the first-run
wizard no longer asks for them:

```sh
omh setup --profile-pack cto-loop --profile-pack startup-delivery
```

The `cto-loop` pack is an optional CTO, PM, Dev, QA, Security, and Ops
team-shaped preset. It is not installed by default; use it only when the target
Hermes workspace benefits from visible role files.

Pin a durable coding-owner preference (optional — interactive setup never
asks; by default Hermes asks at the first coding request):

```sh
omh setup --default-executor claude-code
```

Supported values are `choose`, `hermes`, `codex`, `claude-code`, `generic`,
`omx-runtime`, `omo-runtime`, and `omc-runtime`. This flag exists for
wrappers, scripts, and users who want a standing default instead of the
per-request question. Legacy `OMH_SETUP_PROFILES=1,3` still maps to setup
profile categories for automation that already uses it, but new scripts should
prefer `OMH_DEFAULT_EXECUTOR`.

Record a Hermes-facing operating model only when a specific profile should
start from that collaboration posture:

```sh
omh setup --operating-model coding-runtime-team
```

Operating models are explicit advanced defaults, not installed workers and not
first-run wizard choices. They tell Hermes how to bias routing and status
narration for a particular profile; most users should let Hermes choose the
right pattern per request:

| ID | Use when |
| --- | --- |
| `solo-operator` | One operator wants safe defaults and explicit executor choice. |
| `small-team` | A small team wants product, technical, QA, and release ownership to be visible in chat. |
| `research-ops` | Hermes should favor research, strategy, and meeting preparation instead of coding. |
| `coding-runtime-team` | Hermes should prepare Hermes/OMX/OMO/OMC runtime handoffs with runtime templates and observed ladder status. |

Inspect the available models with:

```sh
omh profile list
omh profile inspect coding-runtime-team
omh profile inspect cto-loop
```

Use a profile pack only when you also want visible role files installed under
Hermes. The setup profile persists the stable `operating_model_id` and resolves
the catalog entry when rendering summaries, so catalog copy can evolve without
rewriting user state. Operating models alone do not install role files and do
not prove any runtime execution.

Choose installer/setup output language during bootstrap:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_LANG=ja sh
```

Supported values are `en`, `ko`, `ja`, and `zh`. The same setting can be passed
directly to setup with `omh setup --language zh`.

Skip Hermes config registration during setup:

```sh
omh setup --skip-apply
```

Advanced one-shot compatibility mode can run setup from the installer, but it
is not the default download path:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_RUN_SETUP=1 OMH_RUN_DOCTOR=0 sh
```

Use the active Python environment instead of the default isolated venv:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_INSTALL_MODE=python OMH_PIP_ARGS= sh
```

Customize the isolated install locations:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_VENV_DIR="$HOME/.local/share/omh/venv" OMH_BIN_DIR="$HOME/.local/bin" sh
```

Pass current `omh setup` flags only when that advanced one-shot mode is
explicitly enabled:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_RUN_SETUP=1 OMH_SETUP_ARGS="--dry-run" sh
```

`OMH_SETUP_ARGS` is an advanced escape hatch. Normal install recipes should run
`omh setup ...` as a separate command.

## Uninstall

Remove OMH-managed local state and Hermes integration files:

```sh
omh uninstall
```

This unregisters `~/.omh/skills` from Hermes config, removes `~/.omh`, removes
the managed `~/.hermes/plugins/omh` plugin bundle when it has an OMH manifest,
removes generated team role files recorded in OMH team-profile manifests, clears the
same registration and managed artifacts from every Hermes bot profile
under `~/.hermes/profiles/` (through the same manifest-checked refusals as the primary
home), and removes the install.sh-managed `omh` command venv/link when the current
command is running from that managed venv. It does not delete unrelated Hermes files,
unrelated plugins, unrelated agents, or pipx/development Python environments
that OMH cannot safely identify as install.sh-managed.
If `omh` still runs after uninstall, that means the command package is still on
`PATH`; remove it with the installer-managed venv, pip, or pipx environment
that installed it.

### Package-manager command removal

Removing the command package preserves OMH state, including `~/.omh`, reviewed
memory, installed skills, and Hermes registration. Use the matching native
command when only the CLI package should be removed:

| Installed with | Remove command |
| --- | --- |
| Homebrew | `brew uninstall omh` |
| Bun | `bun remove -g oh-my-hermes` |
| npm | `npm uninstall -g oh-my-hermes` |

For a complete removal, run `omh uninstall --all` first to remove OMH-managed
state and Hermes integration, then run the package-manager remove command.

The npm/Bun launcher keeps the current exact wheel plus the two most recently used caches
and removes abandoned staging directories after 24 hours. `OMH_CACHE_DIR`
overrides these defaults:

- macOS: `~/Library/Caches/oh-my-hermes/npm`
- Linux: `$XDG_CACHE_HOME/oh-my-hermes/npm`, falling back to
  `~/.cache/oh-my-hermes/npm`
- Windows: `%LOCALAPPDATA%\oh-my-hermes\Cache\npm`

The package manager and `omh uninstall --all` preserve this external launcher
cache. After all `omh` processes stop, remove the platform directory manually
when complete removal must include cached wheels.

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
