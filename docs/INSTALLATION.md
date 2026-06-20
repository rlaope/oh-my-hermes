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
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
omh doctor
```

First-run expectation:

1. `omh setup` installs the managed skills and records safe defaults.
2. `omh doctor` checks local registration and points to the next repair action.
3. You restart or reload Hermes Agent.
4. You ask Hermes: `Use OMH request-to-handoff for: I want to safely add a feature to this repo.`

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

## What Setup Changes

OMH's setup footprint is intentionally bounded:

- It installs managed Hermes-visible skills and records local status contracts.
- It can repair or reapply managed `skills.external_dirs` when a Hermes
  profile drifts.
- It keeps CLI output available for setup, doctor, update, and wrapper
  backends.
- It does not patch Hermes core, run hidden coding work, or turn a prepared
  handoff into observed execution.

The curl installer intentionally stops before setup. It installs the isolated
command package and `omh` executable only. `omh setup` is the explicit,
repairable step that installs generated managed skills and registers them with
Hermes through `skills.external_dirs`.
When `omh setup` is run in a real terminal, it opens a small colored wizard that
chooses the setup language, connects OMH to the target Hermes profile, asks for
one simple default coding agent suggestion (`Codex`, `Claude Code`, or
`Hermes`), installs the OMH status helper, and then prints a human-readable
summary. For a first install, pressing Enter through the recommended choices is
the intended path. Advanced setup only asks about optional tool bridge
preferences. Team/profile packs and operating models stay available as explicit
commands or flags, but setup does not make a user lock the whole organization
shape during first install. In non-interactive shells it uses safe defaults and
prints a concise step-by-step summary. Use
`omh setup --json` or `OMH_OUTPUT=json omh setup` for the full
machine-readable payload.

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
readiness, target topology, current or default coding agent, and evidence
state. Skill counts, setup inventory, token metadata, and deep diagnostics are
left to `omh doctor`, `omh_status`, and machine-readable HUD JSON. A quiet idle
line looks like
`[omh] v1.0.1 | plugin:ready | target:single | coding-agent:idle(ask)`.
The plugin also exposes `omh_context` for a compact OMH mental model plus
generic-tool checkpoint, `omh_interact` for shell-free chat responses and
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

For native menu bar or status-widget integrations, use the platform-neutral
view model:

```sh
omh menubar status
```

`omh menubar status` itself emits `menubar_status/v1` JSON with separate
`hermes_agents` and `external_coding_executors` sections, friendly labels such
as `OMH connection: Ready`, `Hermes targets: 2`, `Coding agent: Codex`, and
`Open mode: Ask before opening Codex`, plus source/model icon IDs with tooltip
text. It also includes `display.menu_cards`, a compact Agent Status/Coding
Agent/Evidence card model for native menu bar surfaces. The Agent Status card is
a small `Agent | PID | Status` list. Codex and other coding tools are external
executors, not Hermes agents. Without an explicit process overlay or local
process observation, the payload reports configured/prepared state only and
shows PID as not observed.

On macOS, a normal user-scope `omh setup` also attempts to build and start the
small OMH menu bar helper when `swiftc` is available. The helper lives under
`~/.omh/menubar`, is started with a user LaunchAgent, and refreshes the same
`omh menubar status --observe-local-processes` payload. The visible menu is
intentionally grouped as Agent Status, Coding Agent, and Evidence sections
instead of a raw text list, and it shows process/PID detail only when a fresh
overlay or explicit local observation saw that process. Use explicit commands
when you want to manage it yourself:

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
merged.

MCP bridge setup is also optional and intentionally conservative:

```sh
omh setup --with-mcp
omh mcp manifest
omh mcp config-recipe --host claude-code
omh mcp config-recipe --host codex
omh mcp config-recipe --host opencode
omh mcp config-recipe --host cursor
# wrapper/host adapters can record observed host load when they see it:
omh mcp observe-host --host hermes-agent --session <session-id> --event host_load --evidence-ref <host-log-ref>
```

This records `mcp_mode: bridge_requested` in setup state and keeps
`observed: false` until a Hermes/MCP host records a concrete load or tool-call
event. `omh mcp manifest` prints the generic stdio MCP bridge contract, and
`omh mcp config-recipe --host ...` prints host-shaped copy-paste snippets for
common MCP-capable environments without mutating those host config files. The
bridge exposes only local `omh_status`,
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
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
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
omh release product-readiness --version 1.0.1 --json
omh release evidence-bundle --version 1.0.1 --write --json
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

Use `omh release product-readiness --version 1.0.1 --json` when you want a
single release-candidate card that combines skill content, G1-G10 use-case
readiness, parity contracts, and release checklist shape. It is still local
contract evidence, not live Hermes chat or executor evidence.

Use `omh release evidence-bundle --version 1.0.1 --write --json` when you want
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
hermes skills inspect rlaope/oh-my-hermes/skills/oh-my-hermes
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

By default this installs the preview channel from the `main` branch archive.
For pinned stable installs, pass a release version after the matching
`v<version>` tag exists:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

For custom release archives or local package sources accepted by `pip`, pass
`OMH_PACKAGE_URL`.

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
Chinese, Spanish, French, and German operator requests. The layer expands known
phrases into canonical routing signals, includes `locale:<code>:<label>` in the
matched evidence for scored recommendations, and never calls external
translation services.

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
Human-facing maintenance and catalog commands print readable terminal summaries
by default: `omh install`, `omh update`, `omh uninstall`, `omh apply`,
`omh list`, `omh recommend`, `omh playbook ...`, `omh profile ...`,
`omh probe`, and `omh snippet --output`. Use `--json` on those commands, or set
`OMH_OUTPUT=json`, when a wrapper or automation needs the complete payload.
Backend/control-plane commands such as `chat`, `coding`, `runtime`, `goal`,
`loop`, `memory`, `state`, `harness`, `release`, and `demo` print JSON by
design because they are wrapper contracts rather than the normal human chat
surface.
`omh runtime status` should show the local runtime artifact directory and the
latest install/apply/doctor state when those commands have run. `omh probe`
reports observable Hermes capability surfaces without mutating Hermes internals.
For MCP, `omh probe` reports the bridge server, setup preference, runtime tool
call observation, host session observation, and host config separately:
`mcp_preference` means `omh setup --with-mcp` was requested in OMH local state,
`mcp_bridge_server` means the installed command package exposes `omh mcp serve`,
`mcp_bridge_runtime` means OMH has observed a local MCP bridge tool call, and
`mcp_host_session` means a host or wrapper recorded load/session evidence with
`omh mcp observe-host`. `mcp_host_config` only means a Hermes MCP config file
such as `.mcp.json` or `mcp.json` exists. `omh mcp config-recipe --host
claude-code|codex|opencode|cursor|generic` can prepare the matching config
shape, but a pasted config snippet is still not runtime evidence. These fields
do not prove connector invocation, coding dispatch, implementation, review, CI,
merge, or unrecorded host-specific MCP load unless separate runtime evidence
records that event.
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
coding agent. If a wrapper or operator chooses the explicit backend action,
`omh worktree prepare` can create the local Git worktree and record
`omh_worktree_observation/v1`; that still proves workspace isolation only, not
executor dispatch or implementation.

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
   already starts with the visible OMH marker, such as `[omh] web-research`;
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
14. For a coding profile that has not been observed before, the wrapper can run
   `omh coding executor-readiness --executor <profile>` once and cache
   `executor_readiness/v1`. If the probe reports `missing` or `blocked`, ask the
   user to choose another coding agent, configure PATH, continue in Hermes, or
   keep a prompt/runtime handoff. Retry only after that state changes. Readiness
   is not dispatch, implementation, review, CI, or merge evidence.
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

Check the selected coding agent once before first dispatch:

```sh
omh coding executor-readiness --executor codex
omh coding executor-readiness --executor claude-code
omh coding executor-readiness --executor omx-runtime
```

If the result is `missing` or `blocked`, keep the handoff prepared and ask the
operator whether to choose a different coding agent, configure PATH, continue in
Hermes, or use a prompt/runtime handoff. Do not treat this probe as proof that
the coding agent ran.

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
- plugin `omh_interact` returns the same `chat_interaction/v1` envelope and can
  record a metadata-only wrapper session when Hermes supplies host/session
  metadata.
- `omh chat interact --source discord "<message>"` or
  `omh chat interact --source slack "<message>"` returns a
  `chat_interaction/v1` envelope with a renderable `chat_response/v1`.
- Common non-English requests should preserve the user's original text while
  routing through deterministic locale hints when a tested phrase matches. For
  example, Japanese or Chinese payment-failure reports route to
  `feedback-triage`, French safe-feature requests route to a plan surface, and
  Spanish issue-to-PR requests route to a request-to-handoff playbook without
  claiming machine translation happened.
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
  or observes the workspace action. `omh worktree prepare --repo <repo> --task
  "<task>"` is the explicit local backend action for creating the Git worktree;
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

Most users should run only `omh update`. When `omh` is running from the default
install.sh-managed venv, the command first updates the command package from the
recorded preview/stable package source, re-enters the updated CLI, refreshes the
managed skills, and records a concise update log. If `omh` is running from a
pip, pipx, distro, or custom Python install that OMH cannot safely mutate, the
update still refreshes workflows but prints
`OMH command: not updated (workflows only)` plus the installer command needed to
update the CLI itself. Successful command package updates print a compact line
such as `OMH command: 1.0.0 -> 1.0.1 (updated)` or
`OMH command: main@old -> main@new (updated)` before the workflow summary.

Advanced operators can still pin or test a different source with
`omh update --channel stable --version <version>` or
`omh update --channel local --from-skills-dir ./skills`, but those flags are for
release validation, fixtures, or intentional rollback testing. Local
modifications block updates unless `--force` is supplied.

Run `omh doctor` after an update. Use `omh setup` only when doctor reports that
Hermes registration needs repair, then restart Hermes Agent. Rerun the installer
manually only when `omh update` says the command package was not updated, or
when you intentionally want a one-shot reinstall from a specific source ref. The
installer passes command-package update evidence into OMH so the state log can
show version/ref movement such as `1.0.0 -> 1.0.1` or `main@old -> main@new`
when `OMH_SOURCE_REF` is provided:

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

Record a default coding agent during setup:

```sh
omh setup --default-executor claude-code
```

Supported values are `choose`, `hermes`, `codex`, `claude-code`, `generic`,
`omx-runtime`, `omo-runtime`, and `omc-runtime`. The interactive wizard
intentionally shows only `Codex`, `Claude Code`, and `Hermes` so first setup
stays understandable. Use the wider flag values only for wrappers, scripts, or
advanced runtime profiles. Legacy `OMH_SETUP_PROFILES=1,3` still maps to setup
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
removes generated team role files recorded in OMH team-profile manifests, and
removes the install.sh-managed `omh` command venv/link when the current command
is running from that managed venv. It does not delete unrelated Hermes files,
unrelated plugins, unrelated agents, or pipx/development Python environments
that OMH cannot safely identify as install.sh-managed.
If `omh` still runs after uninstall, that means the command package is still on
`PATH`; remove it with the installer-managed venv, pip, or pipx environment
that installed it.

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
