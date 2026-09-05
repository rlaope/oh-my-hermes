<p align="center">
  <img src="assets/oh-my-hermes-wordmark.png" alt="OH-MY-HERMES" width="100%" style="display:block;max-width:none;height:auto">
</p>

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-desktop.gif" alt="Hermes Desktop running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes Desktop, with oh-my-hermes.</b><br>Pick a workflow; Hermes clarifies before it builds.</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/hermes-cli.gif" alt="Hermes CLI running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes CLI, with oh-my-hermes.</b><br>The same workflows, in your terminal.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-messenger.gif" alt="Hermes messenger app running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes messenger app, with oh-my-hermes.</b><br>Ask in a thread; the run reports back there.</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-setup.gif" alt="omh setup installing the OMH workflows" width="380" height="266"><br>
      <sub><b><code>omh setup</code>, one command.</b><br>Installs the workflows and connects them to Hermes.</sub>
    </td>
  </tr>
</table>

# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent" src="https://img.shields.io/badge/Hermes%20Agent-NousResearch-6f42c1?logo=github"></a>
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="OMH stars" src="https://img.shields.io/github/stars/rlaope/oh-my-hermes?style=flat&logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent stars" src="https://img.shields.io/github/stars/NousResearch/hermes-agent?style=flat&logo=github"></a>
</p>

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>Install once. Keep Hermes. Add a stronger operating layer.</strong>
  <br>
  <em>Planning, research, creation, coding handoffs, operations, and project memory with explicit evidence boundaries.</em>
</p>

<p align="center">
  <img src="assets/oh-my-hermes-agent-poster.png" alt="Oh My Hermes Agent poster" width="720">
</p>

<p align="center">
  <strong>oh-my-hermes</strong> (OMH) turns a normal
  <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a>
  request into a clear capability, a useful next step, and an honest record
  of what actually happened — strengthening the workflow you already use,
  never replacing Hermes or hiding a coding executor behind it.
  <br><br>
  OMH is the operating layer above Hermes-native skills: it frames the
  problem, picks the workflow and evidence gates, and runs native skills
  as capabilities inside that governed path.
</p>

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md) ·
[Agent Install](INSTALL_FOR_AGENTS.md) ·
[GitHub Pages site](site/index.html)

> [!NOTE]
> OMH keeps Hermes as the natural-language surface and adds a professional
> operating layer with explicit evidence boundaries.
>
> <p align="center">
>   <img src="assets/omh-terminal-boot-banner.png" alt="OH-MY-HERMES terminal banner listing available tools, grouped skills, OMH specialists, infrastructure, and the model pool on Hermes Agent" width="1080">
> </p>

> [!TIP]
> Be with us!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Updates for <code>oh-my-hermes</code> are shared on <a href="https://x.com/rlaope">@rlaope</a> on X, alongside release notes and project news.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Follow <a href="https://github.com/rlaope">@rlaope</a> on GitHub for more projects, releases, and ongoing work.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Join the <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> on Discord to ask questions, share workflows, and talk with other users.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Built with AI agents <a href="https://github.com/frirenai"><strong>Friren</strong></a> and <a href="https://github.com/sionic-khope"><strong>Killua</strong></a>, collaborators helping ship <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Thank you to <a href="https://nousresearch.com/">Nous Research</a> for creating Hermes Agent.</td>
>   </tr>
> </table>

<br>

## Quick Start

**macOS / Linux:**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

**Or paste this into your AI agent:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

**⭐ Then set it up (required):**

```sh
omh setup
```

**Update:**

```sh
omh update
```

`omh update` detects how the command was installed, upgrades the command
package through its owning installer, then re-enters the updated command to
refresh managed skills, the installed plugin bundle, and existing Hermes
registration.

**Verify or troubleshoot:**

```sh
omh doctor
```

<details>
<summary><b>Other installation paths</b> — Homebrew, Bun, npm, Hermes skill tap, manual fallback</summary>

<br>

> **Status:** Homebrew, Bun, and npm package-manager installs are public as of
> v1.0.6.

**Homebrew:**

```sh
brew install rlaope/tap/omh
```

**Bun:**

```sh
bun install -g oh-my-hermes
```

**npm:**

```sh
npm install -g oh-my-hermes
```

Run `omh setup` after any of these, same as above.

**Hermes skill tap path:**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

**Manual package-manager fallback or removal:**

| Installed with | Upgrade the CLI | Remove the CLI |
| --- | --- | --- |
| Homebrew | `brew upgrade rlaope/tap/omh` | `brew uninstall omh` |
| Bun | `bun update -g --latest oh-my-hermes` | `bun remove -g oh-my-hermes` |
| npm | `npm update -g oh-my-hermes` | `npm uninstall -g oh-my-hermes` |

Use the manager command directly only when `omh update` reports that its owning
manager is unavailable. Removing the command package preserves OMH state. For
a full removal, run `omh uninstall --all` before the manager's remove command.

Maintenance paths such as reconciling a `--full` install back to core live in
[Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core).

</details>

<br>

## What you get

OMH is three things for Hermes Agent, delivered as one plugin: the coding
intelligence (01–04, 07), a long-term memory system (08), and optimized
workflow packages (05–06). One scene each, drawn from the real surfaces.

### 01 · Per-model tuning, task splitting, and stronger coding skills

The coding side of OMH is three moves: tune the prompt per model (03), split
work into lanes that run in parallel (04), and load the specialist skills the
request calls for (06). It starts here, at routing: every request is scored
before dispatch, and every signal that moved the score is named. A rename scores light and goes to the quick lane. "Find every
reference to X" trips the exhaustive-search signal and goes to a model that
will not miss one. Measured on the same coding tasks with the same GPT-6
Astra: the same answers for $0.66 instead of $4.29, in 5 minutes instead of
23.

<p align="center">
  <img src="assets/showcase-01-routing.svg" alt="omh coding complexity scoring two requests, and the measured Astra table: same 18 of 30 solved, $4.29 to $0.66, 23 to 5 minutes" width="1080">
</p>

[Read the benchmark ↗](benchmarks/live-model-tools/v1/README.md)

### 02 · Categories you own, per executor

`ultrabrain`, `deep`, `architect`, `quick`, `writing`, `visual-engineering`:
each is a chain of model + effort, per coding executor, that you can read and
override in one file. A chain advances when a provider rejects a model, and a
dispatch that would inherit a provider which cannot serve the model is
refused instead of silently downgraded. Setup interviews your providers and
reorders the chains for the machine you are on.

<p align="center">
  <img src="assets/showcase-02-categories.svg" alt="omh coding category-maestro show: per-executor category chains, one operator override, and a refused dispatch" width="1080">
</p>

[Read the routing docs ↗](docs/FANOUT.md)

### 03 · Prompting tuned per model family, and measured

Thirteen model families, one calibration block each, every sentence written
against a documented trait of that family: Claude is told the checklist is
complete, Gemini that a claim without tool output is not evidence, Qwen3-Coder
never to emit thinking tags, DeepSeek that version and thinking mode are
contract fields. GPT-6 Astra gets its own exact-model contract and block. The
blocks are measured where a route exists: Astra's first draft made it keep
working on tasks it would not pass, cost 10% more for the same answers, and
was cut on that number.

<p align="center">
  <img src="assets/showcase-03-calibration.svg" alt="One calibration line per model family, the gpt-6-astra model contract, and the measured revision" width="1080">
</p>

[Read MODEL_OPTI.md ↗](MODEL_OPTI.md)

### 04 · Parallel where it is safe, typed when it comes back

`ulw-work` splits an accepted plan into units that never share a file, gives
each one its own worktree branched from one pinned SHA, and lets a unit issue
its tool calls in one turn. Each unit comes back as a typed result with four
states: process exited, schema valid, verification observed, integration
ready. Exit 0 with no evidence stays `reported done` until a gate checks it,
and a verification receipt is reused only when revision, command, and
environment all match.

<p align="center">
  <img src="assets/showcase-04-parallel.svg" alt="An ulw-work fan-out: three units with disjoint files, one worktree each, typed states, and the tool calls issued in one turn" width="1080">
</p>

[Read the fan-out contract ↗](docs/FANOUT.md)

### 05 · The Oh-My-Hermes interface, and Hermes Agent workflows

The interface is the Hermes terminal with an OMH dock under the prompt and a
phase todo above it; the workflows are the `ulw-*` engines and every `omh-*`
skill, routed from chat. One row per delegated lane: model, effort, turn,
tokens, cost, updated live. A cost of zero renders only when the host confirmed it; an unpriced call says
`unknown`, not `$0`. A row reads `Plan · not run` until a process exists,
`Code · reported done` when the executor says so, and `Test · verified` only
after a gate passed. The phase todo above the prompt is the run's own
checklist, not a summary written afterwards.

<p align="center">
  <img src="assets/showcase-05-hud.svg" alt="The OMH HUD: per-lane rows with model, effort, turn, tokens, cost provenance, and evidence state, plus the phase todo" width="1080">
</p>

[Read the evidence rules ↗](docs/CAPABILITY_IMPACT.md)

### 06 · Expert skills seep into the run

You never invoke an expert. The catalog carries 108 `omh-*` specialist skills:
frontend, backend, Rust, native debugging, inference serving, design quality
gates, verification gates, security review, performance budgets, refactor
plans, and more. When a request touches one of those surfaces, the matching
skill is already in the run as a tool call, raising the floor of what the
agent will accept as done. Say it in English or Korean; the router picks the
specialists.

<p align="center">
  <img src="assets/showcase-06-skills.svg" alt="Expert omh-* skills loading into one run as tool calls, an orbit of specialists around the run, and three numbers" width="1080">
</p>

[Browse the catalog ↗](docs/WORKFLOWS.md)

### 07 · The architecture in one picture, then improved in phases

Ask for a picture of the repo and `codebase-uml` draws it from the code:
packages, modules, and every import edge, with the cycles marked. The
findings come ranked, and `refactor-plan` turns the top ones into phases that
each land as one PR, behavior-locked by the tests, and abort the moment a lock
breaks. The before and after are measured on the tree, and the dock shows
each phase as it runs, and whether anything checked it.

<p align="center">
  <img src="assets/showcase-07-architecture.svg" alt="codebase-uml draws the repo with two cycles, the findings and a phased refactor plan beside it, the measured before and after, and one dock row per phase" width="1080">
</p>

[Read the refactor plan skill ↗](skills/omh-refactor-plan/SKILL.md)

### 08 · A long-term memory that a reviewer admitted

Nothing is remembered silently. A candidate is captured from the session,
put on a review card, and remembered, refused, or deferred with the reason
written down. An approved record carries its provenance and a review-due
date; confirming it resets the clock, silence ages it from active to
reference to archive. The next session gets a recall pack ranked for its task
and cut to a token budget, with conflicts and duplicates resolved. Hermes'
own memory is never read or patched; this store is OMH's, file-backed and
reviewed.

<p align="center">
  <img src="assets/showcase-08-memory.svg" alt="Long-term memory: admission cards, one record's lifecycle, attention tiers, and a budgeted recall pack for the next session" width="1080">
</p>

[Read the memory model ↗](docs/MEMORY.md)

<br>

## The OH-MY-HERMES terminal

Bare `omh` opens Hermes — the same door as `hermes` — wearing the OMH
identity:

```sh
omh
```

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/omh-terminal-boot-hud.png" alt="The OH-MY-HERMES boot"><br>
      <sub><b>The OH-MY-HERMES boot.</b></sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-terminal-ulw-work-session.png" alt="An ulw-work run"><br>
      <sub><b>An <code>ulw-work</code> run.</b></sub>
    </td>
  </tr>
</table>

What the terminal shows while OMH workflows run:

- **Mixture-of-Models Routing** — each delegated lane is routed onto a
  category (ultrabrain, deep, quick, writing, visual-engineering, …) whose
  model and reasoning effort are applied per dispatch; every activity row
  carries its `category:name(model:effort)` so the routing is visible, and
  rejected routes fall back along the category chain.
- **Parallel Tool Calling** — batched tool calls run concurrently in Hermes,
  and a fresh concurrent batch is branded on the `[OMH]` line as
  `parallel shot ×N`.
- **Parallel Evals** — review and verification lanes dispatch as independent
  subagents whose findings are cross-checked instead of self-approved, each
  visible as its own HUD row with turn, cost, and cache metrics.
- **Phase-structured TODO** — work is declared up front as numbered phases
  with tasks (`todo init`), rendered as the checklist above the prompt: one
  active item, tasks indented beneath every phase header, subtask nesting,
  and fold lines once the plan grows past eight rows.

<br>

## Recommended models

OMH ships with these editable, ordered recommendation chains. Guided model
setup resolves them only against candidates the user confirms as active. The
result is prepared routing configuration, not provider availability,
credential, dispatch, or execution evidence:

| Category alias | What it is for | Editable recommendation order |
| --- | --- | --- |
| `ultrabrain` | Deepest reasoning | GPT-6 Astra, then GPT-5.6 Sol (xhigh) |
| `deep` | Strong default tier | GPT-5.6 Terra, then DeepSeek V3.2 (high) |
| `architect` | Architecture and system design | Claude Fable 5.1, then Claude Mythos 5.1, then Claude Fable 5, then GPT-6 Astra, then GPT-5.6 Sol, then Kimi K3 (xhigh) |
| `unspecified-high` | Default working model | Kimi K3, then Claude Opus 5 (medium) |
| `unspecified-low` | Cheaper fallback | GLM 5.3, then GLM 5.2, then GLM 5.2 Ultrafast, then DeepSeek V3.2, then Claude Opus 5 (low) |
| `quick` | Short tasks | GLM 5.3 Flash, then GLM 5.2 Ultrafast, then Kimi K3, then GPT-5.6 Luna, then Claude Fable 5.1, then Claude Mythos 5.1, then Claude Fable 5 (low) |
| `writing` | Prose and docs | Kimi K3, then Qwen3-Coder, then Gemini 3.1 Pro (medium) |
| `visual-engineering` | Frontend and visual | Claude Fable 5.1, then Claude Mythos 5.1, then Claude Fable 5, then Kimi K3 (high) |
| `artistry` | Unconventional work | Gemini 3.1 Pro, then Claude Fable 5.1, then Claude Mythos 5.1, then Claude Fable 5, then Kimi K3 (high) |

Want to try the Ultrafast tier — Kimi K3 Ultrafast (300 TPS) and
GLM 5.2 Ultrafast (600 TPS)? They are served on
[OpenGateway](https://opengateway.ai/).

Every chain above is user-editable without touching code. The chains are
managed in one file — `omh setup` seeds it:

```sh
$ cat ~/.omh/routing/model-chains.json
{
  "categories": {},
  "schema_version": "mixture_chain_overrides/v1"
}
```

Empty `categories` keeps every shipped default above live. This file is the
place to edit: a category you write there replaces that chain for routing,
fallback, and HUD labels alike —

```json
{
  "schema_version": "mixture_chain_overrides/v1",
  "categories": {
    "architect": [
      {"model": "claude-fable-5-1", "reasoning_effort": "xhigh"},
      {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}
    ],
    "quick": [
      {"model": "kimi-k3-ultrafast", "reasoning_effort": "low"},
      {"model": "glm-5.2-ultrafast", "reasoning_effort": "low"}
    ]
  }
}
```

Check the chains currently in effect with `omh model-chains show`. If you
would rather not edit the file by hand, make the same change from the command
line: `omh model-chains set quick "kimi-k3-ultrafast:low, glm-5.2-ultrafast:low"`.
When an alias uses a provider-specific wire ID, map it once in
`~/.omh/routing/model-providers.json` with
`model_provider_routes/v1`; `set`, `status`, fallback, and HUD then report the
complete alias/provider/wire-model route. OMH stores only provider IDs, never
provider credentials.

Every account differs, so the interactive `omh setup` also asks which
providers the machine holds (config keys and env-key names suggest them;
you can add more) and whether you have a Claude Code subscription, and
records the answer in `~/.omh/routing/providers.json`
(`provider_entitlements/v1`). Each chain is then reordered so the entries a
confirmed provider can serve lead; nothing is removed, nothing is invoked to
check, and the Claude Code subscription only seeds the Claude Code `--model`
preference for the Maestro lane, because Hermes itself cannot spend it.

Ask Hermes to **set up my models** to review or change them. These are editable
preferences, not benchmark results. See
[Guided Model Setup](docs/INSTALLATION.md#guided-model-setup) for the detailed
setup, fallback, provider, and ownership rules.

Coding delegation dispatch (`omh coding run` / `omh coding fanout dispatch`)
— the Maestro lane that spawns Claude Code or Codex directly — has the same
category dial as its own sibling file. Route it per work category with

```sh
$ omh coding category-maestro set codex ultrabrain gpt-5.6-sol:xhigh
$ omh coding category-maestro interview   # guided walk, Enter keeps each chain
$ omh coding run --owner codex --category ultrabrain --goal ...
```

which edits `~/.omh/routing/category-maestro.json`
(`omh_category_maestro/v1`); `omh coding category-maestro show` prints the
effective table with operator overrides marked, and the interactive
`omh setup` offers the same walk. An explicit `--model` on a run always wins,
and `~/.omh/routing/dispatch-models.json` remains the per-owner default used
only when no route resolves at all (for the strongest Claude Code tier, set
`"claude-code": "opus"` there). See `docs/FANOUT.md` (Category-maestro and
Dispatch-model preference) for schemas and the full precedence order.

<details>
<summary><strong>Or paste this into Hermes or another coding agent</strong></summary>

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

</details>

<br>

## Ultra-Skills

<p align="center">
  <img src="assets/omh-character-badge.png" alt="Oh My Hermes character mark" width="170">
</p>

<!-- omh:ulw-inventory:begin (generated: uv run python -m omh.cli docs ulw-inventory; source: src/skills/catalog.py) -->
Nine `ulw-` workflows. Say the trigger in chat — Hermes routes the
rest. Full catalog: [Workflow Reference](docs/WORKFLOWS.md).

| Workflow&nbsp;command | What it does |
| --- | --- |
| ⚡ `ulw-context` | Aligns reviewed project terms, captures confirmed candidates, and interviews the next decision frontier without giving terminology routing authority. |
| ⚡ `ulw-interview` | Asks one question at a time until it knows exactly what you want. |
| ⚡ `ulw-research` | Digs through real code and the live web, keeps sources, and verifies anything doubtful. |
| ⚡ `ulw-plan` | Builds a reviewed plan: options compared, risks named, done-criteria agreed. |
| ⚡ `ulw-work` | Runs an accepted plan in parallel lanes that never touch the same file. |
| ⚡ `ulw-maestro` | Runs a delegated task on Claude Code or Codex — prompt composed from the CLI's own installed skills, spawned live with a dock row and a steerable session. |
| ⚡ `ulw-loop` | Cycles plan → build → review until the goal actually passes. |
| ⚡ `ulw-qa` | Attacks the build with hostile scenarios and fixes what breaks. |
| ⚡ `ulw-perf` | Measures where it is actually slow or expensive, then fixes one hot path at a time. |
<!-- omh:ulw-inventory:end -->

<br>

## What OMH Adds

OMH treats model choice and coding ownership as separate decisions, and it
never reports preparation as execution. Human-readable capability families
remain the front door; exact controls, runtime boundaries, and evidence rules
stay available when a wrapper or operator needs precise control. The full
generated catalog, triggers, harnesses, and evidence rules live in
[Workflow Reference](docs/WORKFLOWS.md).

**Highlights**

| Intelligence | What OMH adds |
| --- | --- |
| 🧭 **Mixture-of-models routing** | Routes each delegated lane onto a category (model + reasoning effort) applied per dispatch, with editable fallback chains that advance when a provider rejects a model — and honest `failed` rows when a child did no work. |
| 🖥️ **Native TUI surface** | The OMH HUD (live delegation rows with category, turn, cost, cache), the phase todo checklist above the prompt, `parallel shot ×N` branding, full-row diff bands, and four managed skins (sky, amber, crimson, mono) you switch from an arrow-key picker with `omh theme` — all installed next to Hermes, never patching it. |
| 📋 **Phase-structured plans** | `todo init` declares phases and tasks before engine work so runs walk a bounded checklist instead of an open-ended reasoning loop. |
| ⚡ **Observed parallel work** | Splits independent work into explicit fanout units with isolated ownership, progress observation, and verification gates. |
| 🎼 **Maestro handoffs** | Prepares handoffs to explicit coding owners and runtime profiles without becoming a hidden executor or treating preparation as execution. |
| 🧠 **Context intelligence** | Projects compact, reviewed repository context without inventing hidden memory or silently changing the selected route. |
| 📚 **Just-in-time learning** | Selects the highest-value learning target for the current blocker and prepares source-backed, application-first guidance without claiming learning already happened. |
| 🔍 **Evidence-bound delivery** | Separates prepared intent, observed runtime activity, and verified outcomes across coding, review, CI, and merge work. |
| 🔎 **Structural code search** | A measured `ast-grep` playbook — structural queries across 28 languages, body-capture bans, grep fallback — injected where executors search code; OMH detects the binary and never runs it. |
| 🗄️ **Project memory system** | A deterministic file-backed memory provider Hermes can load, reviewed project-memory commands (inspect, pack, domain capture), consolidation-scheduling briefs, and memory review skills — never reading or patching Hermes' opaque internal memory. |
| 🛠️ **Coding harnesses & guardrails** | Executor readiness probes, capability snapshots and owner-fit reports on prepared handoffs, code-mode discipline on `execute_code` results, and user-authored toolcall rules that block an off-script tool call with your rule text. |
| ♾️ **Ultra workflow engines** | Parallel delivery lanes with disjoint ownership, measured goal loops with ledgers and real completion gates, and decision-frontier interviews that clarify intent before any engine runs — the ULW engines are listed in Ultra-Skills below. |
| 📦 **A deterministic skill catalog** | 120+ installable workflow skills with a byte-exact generated catalog, routing precision corpora (negative controls included), and drift gates that fail CI on one-character divergence. |

<br>

## Evidence Before Claims

OMH never reports that work happened unless it watched it happen. Every status
you see has two parts: the stage, and how sure OMH is about it.

| You see | It means |
| --- | --- |
| `Plan · not run` | A prompt or plan is ready. **Nothing has run yet.** |
| `Code · running` | An executor is running now, and OMH is watching it. |
| `Code · reported done` | The executor said it finished. Nobody checked the result. |
| `Test · verified` | A test, review, or CI gate actually passed. |

The distinction that matters is the second row from the bottom: an executor
saying it is done is not the same as anything having been checked, and most
tools spell both "complete". Capability impact is reported across separate
dimensions rather than collapsed into one marketing score. See
[Capability Impact](docs/CAPABILITY_IMPACT.md).

<br>

## Documentation

- [Documentation map](docs/README.md)
- [Installation and updates](docs/INSTALLATION.md)
- [Product direction and boundaries](docs/DIRECTION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Capability manifests](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [Roles](docs/ROLES.md)
- [Application cases](docs/APPLICATION_CASES.md)
- [Release and development](docs/RELEASE.md)

<br>

## Development

For a source checkout:

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH is developed in the open as part of
[Team Art & Engineering](https://rlaope.github.io/artengine-lab/). Follow
[@rlaope](https://github.com/rlaope) for project updates.
## Contributors

Thanks to everyone who has contributed to oh-my-hermes.

<a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rlaope/oh-my-hermes&max=100&columns=10" alt="oh-my-hermes contributors" />
</a>
