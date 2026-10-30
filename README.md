<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="oh-my-hermes logo: the oh-my-hermes character in bold black line art on a white rounded-square tile" width="200">

<br>
<br>

**All-in-one package for Hermes Agent. Install once, then just type `dag-ulw`.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** is an operating layer for [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
You keep talking to Hermes. OMH picks the skill and a model for each lane, and runs the work in parallel.<br>
It never patches or replaces Hermes, and it never reports planned work as done.

</div>

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

[Windows and other options →](docs/INSTALLATION.md)

<br>

## What you get

- **The right model for every lane.**<br>
  Each lane is tagged with a work category: `ultrabrain`, `deep`, `visual-engineering`, `quick` and more.<br>
  The category picks that lane's model chain and reasoning effort, and you can edit every chain.<br>
  When a provider rejects a model, the chain moves to the next one instead of silently downgrading.<br>
  `omh model` opens the picker; [see which model runs each lane](docs/INSTALLATION.md#guided-model-setup).

- **`/dag-ulw` graph runs.**<br>
  Your goal becomes a graph of small nodes, and the ready ones run in parallel.<br>
  Each node runs on its category's model and effort; nodes running at once never share a write scope.<br>
  A separate node checks the goal, and failed nodes are repaired before the report.

- **Expert skills on demand.**<br>
  A hundred-plus `omh-*` specialists: frontend, backend, Rust, security review, verification gates.<br>
  You never call them; the router loads the right ones into the run as tool calls.

- **LSP in the loop.**<br>
  Definitions, references and renames come from the language server, not from text search.<br>
  The model renames what the code means, not what the text matches: aliases, re-exports and shadowed names included.<br>
  Off by default; enable `lsp_tools` in the OMH plugin settings.

- **Callers an edit broke, named before the turn ends, opt-in.**<br>
  When an edit changes a Python definition, OMH asks the language server about every file that imports it and hands back the new errors as `path:line` lines.<br>
  Hermes checks only the file it wrote. Measured, the gain is on callers that reach a function through a renamed package re-export, which models without the check missed; they mostly fixed aliased and module-level callers already. `lsp_diagnostics` re-checks a file or glob.<br>
  Off by default; turn on `impact_check` in the OMH plugin settings ([measurement](benchmarks/live-model-tools/v1/README.md)).

- **Long-term memory you can trust.**<br>
  Nothing is remembered silently: each candidate is kept, refused or deferred with a written reason.<br>
  The next session gets a recall pack ranked for its task and cut to a token budget.<br>
  Hermes' own memory is never read or patched.

- **OMH Native.**<br>
  Bare `omh` opens OMH's own TUI on Hermes' gateway; switch its launch look with `/theme`.<br>
  `/dag-ulw` prints the box graph, then a live lane tree with each lane's model, effort and tokens.<br>
  Steer or interrupt an agent from the agent list, run a `!` shell line, and rewind with Esc Esc.

- **Evidence before "done".**<br>
  Every status names its stage and how sure OMH is about it.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  A run counts as verified only when a test, review or CI gate actually passed.

<br>

## DAG-ULW

**Just type `/dag-ulw`, and you're a graph engineering master.**

Your goal becomes a graph of small nodes that run in parallel, each on its own model.<br>
A separate node verifies the goal before you get the report.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="The OMH TUI running /dag-ulw: the prompt is typed, the box graph of seven lanes is defined, the lanes run layer by layer on Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 and Kimi K3.1 Pro, and every lane ends accepted" width="900">
</p>

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
>     <td>Built with AI agents <a href="https://github.com/frirenai"><strong>Friren</strong></a> and <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, collaborators helping ship <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Thank you to <a href="https://nousresearch.com/">Nous Research</a> for creating Hermes Agent.</td>
>   </tr>
> </table>

> **Sponsors** These are our sponsors. They help keep oh-my-hermes going.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> sponsors oh-my-hermes, thank you for backing open source.<br>One OpenAI-compatible endpoint for many model providers, with automatic failover.</td>
>   </tr>
> </table>

<br>

## Others

[Docs](docs/README.md) · [Installation](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Website](https://omher.app/)

<details>
<summary><b>Install options</b></summary>

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
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

**Update:**

```sh
omh update
```

`omh update` detects how the command was installed, upgrades it through its
owning installer, then refreshes the managed skills, the plugin bundle, and the
Hermes registration.

**Verify or troubleshoot:**

```sh
omh doctor
```

```sh
# Set the model per work category (arrow keys: category, ←→ head model, -/+ effort);
# the same picker opens inside the OMH TUI (bare omh) as /omh-model:
omh model
# To onboard a new model family, use this skill in Hermes:
/omh-model-setup
```

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

Bun and npm also need Node 18+ and Python 3.11+ on PATH; Homebrew brings its
own Python. Run `omh setup` after any of these, same as above.

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

<details>
<summary><b>Reference</b></summary>

### Ultra-Skills

<!-- omh:ulw-inventory:begin (generated: uv run python -m omh.cli docs ulw-inventory; source: src/skills/catalog.py) -->
Ten `ulw-` workflows. Say the trigger in chat — Hermes routes the
rest. Full catalog: [Workflow Reference](docs/WORKFLOWS.md).

| Workflow&nbsp;command | What it does |
| --- | --- |
| ⚡ `ulw-context` | Aligns reviewed project terms, captures confirmed candidates, and interviews the next decision frontier without giving terminology routing authority. |
| ⚡ `ulw-interview` | Asks one question at a time until it knows exactly what you want. |
| ⚡ `ulw-research` | Digs through real code and the live web, keeps sources, and verifies anything doubtful. |
| ⚡ `ulw-plan` | Builds a reviewed plan: options compared, risks named, done-criteria agreed. |
| ⚡ `ulw-work` | Runs an accepted plan in parallel lanes that never touch the same file. |
| ⚡ `dag-ulw` | Runs a big job as a graph of small parallel nodes, verifies the goal with a separate node, and repairs what failed. |
| ⚡ `ulw-maestro` | Runs a delegated task on Claude Code or Codex — prompt composed from the CLI's own installed skills, spawned live with a dock row and a steerable session. |
| ⚡ `ulw-loop` | Cycles plan → build → review until the goal actually passes. |
| ⚡ `ulw-qa` | Attacks the build with hostile scenarios and fixes what breaks. |
| ⚡ `ulw-perf` | Measures where it is actually slow or expensive, then fixes one hot path at a time. |
<!-- omh:ulw-inventory:end -->

#### Recommended set

Type these at the Hermes prompt. The `ulw-` prefix picks the workflow; the
rest is your request in plain words.

**1. Shape it.** `ulw-interview` when the idea is still fuzzy, `ulw-plan` when
the change is known but risky.

```text
❯ ulw-interview: I want a CLI that tracks the ISS and warns me before it passes overhead
❯ ulw-plan: analyze this project's circular dependencies and plan the refactor
```

**2. Build it.** `ulw-work` runs the accepted plan in parallel lanes that never
edit the same file.

```text
❯ ulw-work: run the accepted plan
```

**3. Finish it.** `ulw-loop` keeps cycling until the gate you name passes.

```text
❯ ulw-loop: keep going until npm test passes
```


### How it works with Hermes

Hermes Agent already runs the loop. OMH decides what goes into it: which
model and effort each lane gets, who owns the code change, which skills
apply, and what counts as done. Two rules hold everywhere: model choice
and coding ownership are separate decisions, and nothing prepared is ever
reported as executed. The generated catalog, triggers, and evidence rules
live in [Workflow Reference](docs/WORKFLOWS.md).

### The workflow

**Understand → Research → Decide → Plan → Execute → Verify → Operate → Learn**

| Stage | What happens |
| --- | --- |
| Understand | Confirm the intent, constraints, project terms, and stop conditions. |
| Research | Replace assumptions with source-backed product, code, or operational context. |
| Decide | Make the options, tradeoffs, and decision owner explicit. |
| Plan | Turn accepted scope, coding ownership, tests, and done criteria into an executable plan. |
| Execute | Dispatch bounded work to the selected owner and track what actually runs; a prepared handoff is not execution evidence. |
| Verify | Base the verdict on observed test results, review findings, CI status, and runtime evidence. |
| Operate | Keep release health, incidents, rollback state, and follow-up work visible. |
| Learn | Promote reviewed, scoped lessons into project memory or workflow improvements. |

**Highlights**

| Intelligence | What OMH adds |
| --- | --- |
| 🧭 **Mixture-of-models routing** | Every delegated lane lands on a category (model + reasoning effort) at dispatch time. Chains fall through when a provider rejects a model, and a child that did no work shows `failed`, never a green row. |
| 🎛️ **Per-family calibration** | Prompting is tuned per model family and generation — GPT-6 Astra, GPT-5.6, Claude 5.5, GLM 5.3, Kimi, Gemini, Qwen, DeepSeek and more — and each tune is kept only while the benchmark pair says it helps. |
| 🗂️ **Categories you own** | Shipped model categories, with `omh model-chains set` to reorder, an entitlement interview that reorders chains per machine, and a live view of what a request would route to before it runs. |
| 🖥️ **Native TUI surface** | The OMH HUD (live rows with category, turns, cost, cache), the phase todo above the prompt, `parallel shot ×N`, full-row diff bands, and a theme of your own — in the OMH TUI bare `omh` opens, never patching Hermes. |
| ⚡ **Observed parallel work** | Independent work splits into fanout units with disjoint file ownership, admission control under provider pressure, typed result sidecars, and verification gates that read what came back. |
| 💸 **Priced cost telemetry** | Token counts and dollar figures on every HUD row and run summary, priced from a rate table that cites its source; an unpriceable run reads `unknown`, never `$0`. |
| 🧠 **Long-term project memory** | A file-backed memory provider Hermes loads, admission and retention policies, reviewer-gated writes, and recall packs with freshness and budget — Hermes' own memory stays untouched. |
| 🔎 **Structural code search** | A measured `ast-grep` playbook (28 languages, grep fallback) and `omh codegraph uml` for a repo-wide architecture picture, injected where executors read code; `omh codegraph tests --changed` names the tests a change reaches ([codegraph commands](docs/CODEGRAPH.md)). |
| 🛡️ **Guardrails you write** | Toolcall rules that block an off-script call with your own rule text, a completion-integrity gate that refuses stubs and skipped tests as evidence, and an approval tier for risky actions. |
| ♾️ **Ultra workflow engines** | Parallel delivery lanes, measured goal loops with ledgers and real completion gates, and decision-frontier interviews before any engine runs — listed in Ultra-Skills above. |
| 📦 **A deterministic catalog** | A hundred-plus installable skills generated from one source, routing precision corpora with negative controls, and drift gates that fail CI on a single divergent byte. |

### Evidence before claims

OMH never reports that work happened unless it watched it happen. Every status
you see has two parts: the stage, and how sure OMH is about it.

| You see | It means |
| --- | --- |
| `Plan · not run` | A prompt or plan is ready. **Nothing has run yet.** |
| `Code · running` | An executor is running now, and OMH is watching it. |
| `Code · reported done` | The executor said it finished. Nobody checked the result. |
| `Test · verified` | A test, review, or CI gate actually passed. |

An executor saying it is done is not the same as anything having been
checked, and most tools spell both "complete". Capability impact is reported
across separate dimensions rather than one marketing score; see
[Capability Impact](docs/CAPABILITY_IMPACT.md). The product A/B lane that
compares Hermes alone with Hermes through OMH has its corpus and offline pilot
in place, and no measured run is published yet:
[`benchmarks/product-ab/v1/README.md`](benchmarks/product-ab/v1/README.md).

### Documentation

- [Documentation](docs/README.md)
- [Installation and updates](docs/INSTALLATION.md)
- [Agent Install](INSTALL_FOR_AGENTS.md)
- [Product direction and boundaries](docs/DIRECTION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Capability manifests](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [Roles](docs/ROLES.md)
- [Application cases](docs/APPLICATION_CASES.md)
- [Model routing, fan-out contracts, and request scoring](docs/FANOUT.md)
- [Fanout executor evidence: sessions, failure diagnostics, capacity (agent/operator reference)](docs/FANOUT-EXECUTOR-EVIDENCE.md)
- [Agent board and native Kanban coordination (agent/operator reference)](docs/AGENT-BOARD.md)
- [Per-model calibration map](MODEL_OPTI.md)
- [Evidence rules and capability impact](docs/CAPABILITY_IMPACT.md)
- [Long-term memory model](docs/MEMORY.md)
- [Codegraph commands](docs/CODEGRAPH.md)
- [Show-reel toolkit](docs/SHOW-REEL-TOOLKIT.md)
- [Processing a very large PDF with Hermes](docs/LONG-DOCUMENT-READING.md)
- [Live model benchmark and measured results](benchmarks/live-model-tools/v1/README.md)
- [Release and development](docs/RELEASE.md)
- [Website](https://omher.app/) · [GitHub Pages site](site/index.html)

### Contributors

<a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rlaope/oh-my-hermes&max=100&columns=10" alt="oh-my-hermes contributors" />
</a>

</details>

## License

MIT, see [LICENSE](LICENSE).<br>
Built in the open with [our contributors](https://github.com/rlaope/oh-my-hermes/graphs/contributors) as part of [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
