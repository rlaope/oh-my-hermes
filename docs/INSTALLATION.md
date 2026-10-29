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

## Runtime state in Hermes profiles (operator reference)

A native Hermes profile must select its own OMH store, or deliberately select
an explicitly shared store. Configure the existing plugin setting in that
profile's `config.yaml`:

```yaml
plugins:
  entries:
    omh:
      settings:
        omh_home: ~/omh-stores/profile-a
```

Setup and update record the resolved store when this setting is unset, for
both the implicit default `~/.omh` and a custom store selected by `--omh-home X`.
A single-profile process reaches the default with nothing named, but a multiplexed
process (a gateway serving several profiles, Desktop `serve`) refuses to load
the plugin for every profile that names no store (#2037). A value already
there is never replaced. A bot profile that already names a store, through
this setting or through `OMH_HOME` in its own `.env`, keeps it untouched; a
profile that names neither is given the primary's resolved store, including
the implicit default; its skill registration may still point at that store.
Uninstall reverses an unchanged binding only under its managed-write rules.
If a profile's `.env` names `OMH_HOME` after OMH gave it X, the setting would
outrank that choice, so setup and update remove it while it still names the
value OMH recorded writing, and say so per profile; a value OMH did not write,
or one changed since, is kept.
`omh doctor` warns (`plugin_omh_home_binding`) when the plugin in the Hermes
home would bind a store other than the one it checked, or names no store and
so is refused in a multiplexed process, and
(`plugin_omh_home_binding:<profile>`) for each profile that names no store,
and for each profile whose `.env` `OMH_HOME` is outranked by a setting OMH
did not write.
Once recorded, the setting outranks an exported `OMH_HOME` for that Hermes
home, and setup does not move it. To switch stores, remove or edit the
setting and run setup with the new `--omh-home`, or run `omh uninstall`
from the old store first.

Two trusted profiles may explicitly name the same directory. That shares OMH
records and home-wide ledgers; it does not make them separate stores. Existing
memory principal/admission checks still apply within shared stores. Different
directories are not an OS sandbox. The dreaming counters and the consolidation
brief stay per profile even in a shared store, and each profile can turn its
brief off with `plugins.entries.omh.settings.dreaming_mode`
([Per-profile dreaming state](MEMORY.md#per-profile-dreaming-state-and-the-mode-setting)).

The copied plugin and package use the same uncached root resolver, in this order:

1. A trusted programmatic/CLI home pair (also supports offline operations).
2. The active profile's `plugins.entries.omh.settings.omh_home`, with the
   existing legacy `config.omh_home` fallback.
3. Legacy `OMH_HOME` from Hermes' active credential scope, verified against
   the host's profile-home-keyed snapshot (its `.env` plus already hydrated
   external sources), never another routed profile's process environment.
   Anonymous scope mappings have no owner identity: mismatching/unverifiable
   values are refused before I/O. Use an absolute profile setting for bindings
   supplied only through an ad hoc in-memory secret mapping.
4. For standalone/launch-owner operation -- the independent `omh` CLI and the
   OMH TUI's HUD reader, which load no Hermes module -- the same setting
   read from the Hermes home's own `config.yaml` by text scan (the user file;
   the managed overlay the native lane validates against is not reachable
   there), then the legacy `OMH_HOME`, then `~/.omh`. The scan follows the
   block shape Hermes writes, last duplicate winning; a `plugins:` section
   written inline that names no `omh_home` reads as an absent setting. Refused
   as a binding error, never a substitute store: a blank or null setting, an
   inline section that does name `omh_home`, an alias or merge key the
   setting could be inherited through, a leaf a YAML loader would not hand
   back as one string (`true`, `123`, `{a: b}`), a tab-indented file, an
   unreadable `config.yaml`, and a `$VAR` other than `$HERMES_HOME` or
   `$HOME` -- this lane has no secret scope to verify a variable against, so
   it will not read one out of the process environment. Each refusal names
   `--omh-home` as the way to run the tool that reads the file. So
   `omh --hermes-home ~/.hermes/profiles/<name> model-chains`, and
   `/omh-model` in the OMH TUI `omh --hermes-home ~/.hermes/profiles/<name>`
   opens, read and write the store the profile's own plugin dispatches from. The CLI has no Hermes dependency and
   retains its explicit `--omh-home`, `--hermes-home`, and `--scope project`
   behavior; an explicit `--omh-home` wins over the setting.

Importing `hermes_constants` alone does not select native operation. A plain
OMH CLI colocated with a compatible Hermes installation still uses process
environment variables. Native home/secret scopes or multiplex mode select the
native lane. Actual registration through Hermes' `PluginContext` or memory
provider collector also marks that **bundle instance** as native: ordinary
single-owner memory loading and later callbacks can run without task scopes.
That marker records only the execution lane, never a profile, home or secret.
Missing scope-probe APIs are ambiguous and fail closed; missing required
callable APIs in an active native host are reported as a bounded
`RuntimeBindingError` before configuration or store reads, not downgraded to
standalone. Internal host import faults still propagate.

A routed profile without a binding, an unscoped multiplex call, and blank or
malformed settings are unavailable with a binding error. They do not create
an empty substitute store. Relative profile settings are anchored at that
profile's Hermes home. `~` still names the OS user's home. Prefer absolute paths;
`$HERMES_HOME` is expanded against the active profile, but an already-expanded
native `${HERMES_HOME}` value that disagrees with that profile is rejected with
an absolute-path diagnostic. Validation follows the winning raw configuration
leaf, including administrator-managed precedence; a shadowed user template
cannot veto a managed absolute setting. Literal paths and setting presence
must also agree with the effective native configuration. Unresolved variables
are rejected. Evidence `project_root` and `workdir` accept literal absolute or
relative paths and the current user's `~`/`~/...`, but not `~other-user/...`
or variable references: model paths never query other OS users, credentials
or environment values.

Explicit empty-string/whitespace home arguments are rejected in both user and
project scope rather than silently selecting a default. This intentionally
tightens the former empty-string fallback: omit the argument (`None` in Python)
to request defaults. Blank configured native bindings never inherit ambient
state. Filesystem failures while resolving runtime homes are also bounded
`RuntimeBindingError`s. Hooks classify failed binding before observation I/O
and then degrade rather than veto, `pre_tool_call` included: a binding fault
means no store was reachable, and the tool-call rules this hook enforces live
inside one. A store that does resolve and whose rules file cannot be read
allows the call as well, by `toolcall_rules`' documented fail-open contract,
so refusing the case where no store can be located at all was the harsher
response to the weaker signal. A rules file that loads and matches still
blocks the call, with its own message. Where the degraded call becomes
visible depends on the hook: Hermes reads a `pre_tool_call` result's `action`
only, so a binding fault there is a silent allow, while a `pre_llm_call`
result's context text is injected into the turn once per turn. That text
names the exception type, which is what keeps a session no profile owns
(`UnattributableSessionError`) distinguishable from a store that was named
and could not be read. For an unreadable profile `config.yaml` the host also
reports the parse error itself, on stderr and as a saved copy of the file.
Direct runtime readers still raise on unreadable state instead of claiming idle.
Evidence child binding failure returns an error without spawning a command.

Native tools/hooks do not treat home-looking model arguments or observation
metadata as permission to choose another store. Legacy model-facing home fields
are explicitly rejected by native tools before observation or store I/O, even
when blank or equal to the active home; omit them. Their schemas retain and
label standalone operator overrides, and trusted offline APIs remain separate.
Standalone observations honor explicit top-level operator homes in both package
and copied-bundle paths; nested observation metadata is never store authority.
Provider and optional
observer/egress/browser instances bind before their first I/O; providers refuse
reinitialization with another Hermes home. Project recall uses the host's
logical cwd rather than a multiplex launch repository; absent/deleted logical
context selects no project. Evidence subprocesses receive only the existing
minimal non-secret environment plus the resolved OMH/Hermes homes. A separately
launched process such as the OMH TUI must likewise receive its owning process's
home pair;
Python context scopes do not cross process boundaries.

Runtime homes are canonicalized (including symlinks) for store identity and
per-home guards. Core project-store paths were already canonicalized; native
logical cwd is passed through without replacing it with the process cwd. Stable
project identity and bound absent-cwd behavior are unchanged.

Repository-scoped artifact defaults are explicit:

| Invocation | `omh_home_named` | `project_artifact_dir` |
| --- | --- | --- |
| Standalone or colocated OMH CLI, no explicit home | false | Logical repository `.omh/`, or user store outside a repository |
| Ordinary single-owner native profile | false | Logical repository `.omh/`, or profile-selected store outside a repository |
| Routed native profile (multiplex or a non-launch home) | true | Profile-selected OMH store; never a launch repository |
| Trusted explicit OMH home/pair | true | Explicit OMH store, including inside a repository |

When logical cwd is absent there is no inferred repository; artifacts use the
selected store. Explicit `--scope project` still selects the logical project's
`.omh`/`.hermes`; without a logical cwd it fails rather than borrowing process
cwd. Naming a runtime store does not change the project's stable identity.

This binding uses native `hermes_constants` profile APIs,
`agent.secret_scope` (including `build_profile_secret_scope`),
`agent.runtime_cwd`, `hermes_cli.managed_scope.load_managed_config`, and the
read-only config loader plus its strict readability validator. A present but incompatible/broken host is
not treated as standalone. Setup/profile synchronization does not stamp one
profile's store into every child or migrate data; configure each routed
profile explicitly before activation. Existing child settings are preserved.

Maintainers can run the opt-in synthetic real-loader suite with a Hermes
checkout's `scripts/run_tests.sh`, passing this repository's
`tests/native/test_profile_runtime.py`, `tests/native/test_review_native.py`,
and `--native-source=/absolute/path/to/hermes`. Use an explicit pytest root/cache
inside the test workspace. The ordinary OMH unittest suite needs no Hermes
installation. These tests distinguish actual turn-start behavior from positive
recall after the native background queue; this change does not alter upstream
turn-start pack invalidation or claim live model delivery.

## Hermes compatibility and support boundaries (operator reference)

Loader observation follows the selected Hermes runtime, not a leftover legacy
venv. An explicit interpreter or `HERMES_PYTHON` override takes precedence; a
direct Python launcher remains supported. Otherwise the PATH launcher is queried
with `--print-runtime-command`, and the observer reads the host's PM-committed
dependency environment before loading PluginManager in a disposable home. It does
not run the state-changing PM bootstrap. A present launcher that fails its printer
reports `hermes_runtime_command_failed`, without falling back to another runtime;
a missing explicit override reports `hermes_python_override_missing`. Finding an
old `venv/bin/python` alone is not proof of the active PM runtime. Successful tool
and hook registration is registration evidence only, not full startup, update,
plugin execution, or browser execution. PM-only browser-skill promotion is not
covered by this loader fix.

The optional browser bridge requires explicit trusted-wrapper opt-in, a bound
principal/session/profile/message identity, and request-bound cache bypasses.
`host_browser_capability()` (also exposed as `ctx.browser_capability()`) reports
API support, not admission. On audited Hermes main revision
`4ea8d23cc9f527332ccb1d55359b27741b6ea51b`, optional browser execution remains unsupported:
`_BROWSER_CONTROL_PRINCIPAL` and `_BROWSER_CONTROL_TRANSPORT_FAMILY` are absent.
The diagnostic is `host_scope_unavailable` with
`host_browser_identity_unsupported` and the missing capability names. OMH does not
manufacture a principal from environment/config/user IDs or bypass approval,
identity, lease, effect, or cache checks. Stable `v0.22.5` supplied the audited
identity/cache APIs, but API support and loader registration do not demonstrate
actual browser acquisition or effect execution on either host.

The compatibility workflow and `tools/check_hermes_compatibility.py` are
maintainer admission checks, not install or support certificates. A local helper
result is not a hosted CI result. The local candidate probe observed a real
stable `v0.22.5` PluginManager, a validated harmless status tool and completed
pre-LLM callback using existing PM dependencies and disposable homes. Fresh PM
provisioning, the hosted stable/main matrix, native Windows execution, Ubuntu
runner execution, and branch-rule enforcement were not observed by this repair.
The local macOS result does not close those gaps. A dirty candidate's receipt
keeps its base SHA and bundle digest separate from an immutable source SHA.

Profile synchronization recognizes genuine Hermes identity markers
(`config.yaml`, `.env`, `SOUL.md`, `profile.yaml`, `auth.json`, or `state.db`),
not directories containing logs/cache alone. Hidden and tombstoned profiles are
excluded. Marker symlinks remain identity claims for existing symlink refusal
and ownership checks, not permission to write through them. A configured child
remains discoverable through its OMH-written `config.yaml` if its initial
`SOUL.md` is later removed; this does not promise recovery after all identity
files are deleted. Setup preserves supported inline-comment `skills:` headers
and existing settings; ambiguous/unsupported YAML shapes are refused rather
than shadowed with duplicate keys.

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

> **Publication status:** Use the npm package and the `rlaope/tap/omh` formula
> as the package-manager distribution sources; check their official metadata
> for the version you intend to install. Publication is not runtime verification:
> it does not establish a successful install, update, or Windows CI result.

Choose one installation path. On macOS and Linux use the universal installer;
on native Windows use the PowerShell installer. The package-manager paths
install the same `omh` command from the published release.

### Universal installer (macOS/Linux)

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

OMH needs Python 3.11+, and the installer finds one itself: it probes `python3`
and the versioned `python3.x` commands, then the usual Homebrew, python.org,
pyenv and uv locations, and reports the interpreter it used. macOS's own
`/usr/bin/python3` is 3.9, so it is skipped rather than used to build a virtual
environment the wheel cannot be installed into. With nothing suitable found and
`uv` already on the machine, the installer has uv install Python 3.12 —
`OMH_PROVISION_PYTHON=0` declines that — and with neither it stops and names the
versions it did find. `OMH_PYTHON=/path/to/python3.12` overrides the search
entirely.

### Windows (PowerShell 5.1+)

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

Windows npm/Bun launcher support is gated by the Windows CI suite and is still
pending: the shared launcher has Windows path, `py -3`, and command-shim
handling, but no Windows job installs the packed tarball and runs the CLI yet
(the packed-tarball smoke runs on Ubuntu and macOS only). Use the PowerShell
installer on native Windows.

### Homebrew

```sh
brew install rlaope/tap/omh
```

### Bun

```sh
bun install -g oh-my-hermes
```

### npm

```sh
npm install -g oh-my-hermes
```

Bun and npm need Node 18 or later on PATH as well as Python 3.11+ (`python3`,
or one of `python3.14` through `python3.11`). The `omh` command they install is
a Node launcher, so a Bun install on a machine without Node fails at the first
`omh` call with `env: node: No such file or directory`. Check both before you
install:

```sh
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 18 ? 1 : 0)' && echo "Node 18+ OK"
python3 -I -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' && echo "Python 3.11+ OK"
```

A bare `python3 --version` that succeeds is not enough: macOS's own
`/usr/bin/python3` is 3.9. Homebrew installs its own Python.

### Set up OMH

After any installation path, install the managed skills and register them with
Hermes:

```sh
omh setup
```

### Workflows in Claude Code, Codex, Cursor, opencode, OpenClaw, or pi

These hosts can load OMH workflows as Agent Skills without Hermes. The
per-host clone installers need no Python and no `omh`. See
[Agent Skills projection](AGENT-SKILLS.md) for the install commands, the
[duplicate copies](AGENT-SKILLS.md#duplicate-copies) that two installers can
leave for Cursor and opencode, and [removal](AGENT-SKILLS.md#removal).

### Open the terminal, and come back to a session

Bare `omh` opens the OMH TUI (described below), and three Hermes session flags
pass straight through on that bare launch:

```sh
omh --resume <session-id>    # reopen one session by id (short form: -r)
omh --continue               # continue the most recent session (short form: -c)
omh -p <profile>             # open a bot profile's own home
```

They are a bare-launch surface only. Passing one together with a subcommand
is an error naming the flag, never a silent no-op, because dropping `-p`
would run that subcommand against a different profile than you selected.

When you close the session (`/quit`, `/exit`, Ctrl+C twice, Ctrl+D), OMH
prints a short card for the session that was open, and only the `omh` way
back:

```text
omh · Fix the login bug

  resume: omh --resume 20261025_101530_ab12cd
```

The first line is the session's title (`untitled session` when Hermes has
not named it). After a blank line, `resume:` reopens it by its whole id,
which always resolves to this session, and a blank line closes the card so
your shell prompt does not sit right under the command. With a profile it carries `-p <profile>`, since a profile
has its own `state.db`. A session in which nothing was said gets one line instead, `omh:
nothing was said in this session, so there is nothing to resume.`, unless
an earlier session of the same launch (before a `/new` or a switch) has
messages: then the card names the newest such one.

Hermes' own exit summary, which names `hermes --tui --resume`, does not
print: the OMH TUI closes with a code of OMH's own, which Hermes' launcher
prints no summary for, and `omh` returns 0 to your shell, as before. A
failure (exit 1, a signal) is returned as it was and prints no card; a
lost gateway names `omh --resume <id>` on its way out. The
OMH TUI records the session it has open, and the Hermes home it runs on, in
a private file `omh` names for the launch and removes once it has read it,
so a resumed session is named too. When Hermes' own terminal opened instead,
its summary prints, and the card follows it for the session the Hermes state
database shows ending with the launch; it prints nothing whenever more than
one session could be the one that closed, or the database cannot be read.

### The OMH TUI

The OMH TUI is OMH's own terminal over your Hermes install. Bare `omh` runs
your `hermes --tui` with `HERMES_TUI_DIR` pointing at a small frontend OMH
ships, so Hermes' launcher still resolves the profile, the session to resume,
the working directory and whether the session is already open somewhere else,
and then starts the OMH frontend in place of its own. Every model call, tool
run and approval decision stays Hermes'; the screen is OMH's.

- Finished replies, tool summaries and notices go to your terminal's own
  scrollback, so selecting, copying and scrolling back work as they do in any
  shell. Only the region under the last line printed repaints, each repaint
  (and each page of a pager) one synchronized update (DECSET 2026), so a terminal that
  supports it shows it whole and nothing flickers. A full redraw (a resize,
  Ctrl+L, `/redraw`, switching or resuming a session) prints the session's
  last 3,000 rows again under one row such as `⋯ 412 earlier messages ·
  /history shows all`; `/history` pages through the whole session. The OMH
  TUI holds a session's last 2,000 messages (a prompt, a reply, its
  thinking, the tool calls between two replies, a notice, a command with its output, a
  steer and a turn's done line are one each); older ones are
  left to the terminal's scrollback until a full redraw clears it, and from
  then on that row says how many `/history` still shows.
- That region holds, from the top: the prompt you just sent (while the
  turn runs, once the prompt itself has scrolled off, as `↳ you: …`, the
  `↳ you:` in the running blue and your words dim, on your sent prompt's band
  with a blank row above it, and a dim `…` where they are cut; a steer you
  sent runs on the same band), the tail of the reply that is still streaming, one slot for the
  OMH plan (or a question Hermes asked, or the slash-command
  menu when it does not open under the composer), the prompts queued behind
  the running turn (`⧗`, up to three named and the rest counted; while the
  turn runs, a muted row under them names the key that sends the oldest one
  into the turn now, as Claude Code does: `ctrl+enter to send now · ↑ to
  edit`, below), the
  composer between two full-width rules as Claude Code draws it (`───`,
  then `❯ …` rows, then `───`, with no side edges or corners),
  one dim info line under it, and, while there are subagents, the agent view
  under that, always expanded (below). A blank row stands between the reply and
  the working row, between the working row's tip and the plan, and between
  the plan and the composer's top rule, wherever the terminal has a row to
  spare for it. Your sent prompt runs on a band to the right edge, a quiet
  tint of the launch look's card edge. On a terminal 6 rows tall the composer keeps its
  top rule and drops its bottom one, so the slot above it still gets its
  two rows; from 7 rows it has both, and under 6 rows (or 20
  columns) the composer is a bare `❯ …` row with no rule. A `/name` you type
  that names one of Hermes' commands or skills is drawn bold in the skill
  colour, in the composer, in your prompt once it is sent and on the
  `↳ you:` row; a resumed session's prompts are drawn again once Hermes
  names the session's commands and skills, when that moves one of the
  prompts a redraw prints. A
  path such as `src/a.py`, a `/name` nothing answers to and
  a word with a slash inside it stay plain. While the draft holds `dag-ulw`,
  `dag ulw` or `/dag-ulw` (any case, as a whole word), its letters run
  violet, magenta, pink and lavender with a brighter band sweeping through
  them, and the composer's two rules are drawn heavy (`━`) in the same
  gradient with a band travelling along them; it ends the moment the word
  goes or the prompt is sent. It moves only on a truecolor terminal with
  motion on, and not while the agent list or the dag tree has the keys; at
  256 or 16 colours it stands still, and with `NO_COLOR`, or on a
  background too close to its colours for the band to show (a mid grey),
  the word and the heavy rules are bold and still. A Korean particle right
  after the word (`dag-ulw로`) keeps it lit, as the router reads it. While you pick from a
  list (a question answered by picking, or the `/sessions`, `/rewind` or bare
  `/model` picker) or search the history with Ctrl+R, the
  composer and its rules are not drawn and the list or the search stands in
  their place, right above the info line. A `/sessions`, `/rewind` or
  `/model` picker sets its list off from its header and its filter row with
  a muted rule, set in by one cell (the header's first, then the filter
  row's), while the list keeps at least three rows. While the agent list or the dag
  tree has the keys the composer keeps its rules and its row says
  `↑↓ browsing · esc to type` instead of the prompt, so nothing moves. A question and the agent list show
  no caret; a picker shows it at the end of its filter row and the search at
  the end of its query, where what you type (an input method's composition
  too) appears. The banner above the
  session is one row: the brand, the version, the session it resumed and the
  working directory. A fresh session says under it where the last one is
  (`last session: <title> · /resume <id> reopens it`), unless you have
  already sent something by the time Hermes lists its sessions; the line
  stays in scrollback like any notice. On a terminal at least as wide as the OH-MY-HERMES block logo
  (100 columns) and 24 rows tall, the start shows the logo above the banner,
  each row in the theme's gradient made to read on the terminal's
  background; `/new` and a switched session do not repeat it, and a full
  redraw shows it again only on top of the whole session. Until the first
  prompt the start fills the screen: the logo and the banner on top, the
  composer and the info line on the bottom rows, the rows between them empty.
- The info line under the composer, two cells in so it starts under the
  composer's text (on the edge on a terminal too small for the rules), is the
  one line under it. On the left it starts with `[⚚ OMH Native]` in the
  launch look's colours, then the session directory's git branch
  (`branch:<name> | !3 ?128`: tracked files changed, then untracked, each
  only when not zero; a detached HEAD by its short sha; nothing outside a
  repository, or on a terminal too small for the rules), read by `git status`
  off the screen's thread after each tool, each turn and every 15 seconds,
  then the input mode or the keys that matter right now; on the right it says
  the session's title once Hermes names it, the model, how full the context
  is and the reasoning effort, as `Fix the login bug ·
  deepseek/deepseek-v4.1-flash · ctx 5% · effort medium` (the context in the warning colour from 80 % full
  and the error colour from 95 %; `ctrl+t effort` while no level is
  known). As the line narrows, the right side's fields shorten and then go
  first; then the branch's name is cut to `…` (24, then 12 cells); then the
  badge shortens to `[⚚ OMH]`, then `⚚`, then goes, and then the branch;
  the mode's label, the agent count and what the next key does (a question's
  or a picker's way out) keep their words until all of those are gone. Room
  the left side leaves goes to the right side's shortest fitting form, so a
  filling context still shows. Between turns in
  the normal mode the left side is the badge and the branch: the launch card names
  `? every shortcut`, and `?` on an empty composer still opens the list that
  names every key. In accept all it reads `⏵⏵ accept all on (⇧⇥ to cycle)` in
  accept's colour and in plan `⏸ plan mode on (⇧⇥ to cycle)` in plan's;
  while Hermes has approvals off on its own it reads `⏵⏵ accept all on (⇧⇥
  plan)`, since Shift+Tab then turns only plan on and off. The composer's rules
  keep their colour in every mode. While a turn runs the line names no key
  for it: the working row offers the interrupt, and the row under the queued
  prompts the send-now key (in accept all and plan the line keeps the label
  and where Shift+Tab goes); while Hermes asks something it names that question's keys (`↑↓
  pick · enter confirms · d or esc denies and stops`), and while a picker or
  the Ctrl+R search is open, its keys (`↑↓ move · enter switches · esc
  closes`). After a first Ctrl+C on an empty composer it says `ctrl+c again
  to exit` for the 2 s a second one exits in, and writes nothing to the
  transcript; during a turn that first press also interrupts it, and the
  second leaves even while `interrupting…` still shows. The interrupt is offered in one place, the working row's `esc
  to interrupt`, and only while Esc does it: in every mode, while the
  composer is empty and nothing else takes Esc (a question, a picker, the
  history search, the agent list, a picked steer or rewind, or the `@` menu
  does), and not again while `interrupting…` shows, so Esc means one thing
  on the screen. When the OMH
  HUD sees a call repeating, or tool calls in flight during a turn, the right
  side says that first (`repeat x4`, `1 tool · 9s`). On a narrower terminal
  the right side gives way first: the session's title, which leads it cut
  to 24 cells (`Rename every production… · deepseek/…`), goes first, then
  the model shortens to its last path
  segment, then that segment loses its first word (`deepseek-v4.1-flash`,
  then `v4.1-flash`; never down to a bare version, so `glm-5.3` stays
  whole), then the model goes, then the effort, then the context,
  and the HUD's counts last. Only then does the left side take shorter
  words: on a line too narrow for what the next key does, the mode's label
  shortens (`⏵⏵ accept`, then `⏵⏵`; `⏸ plan`, then `⏸`) before that is cut,
  and on one too narrow for the label's own words it shortens the same way
  (`⏵⏵ accept · ⏸ plan` with both on); the right side takes whatever room
  the shorter left side leaves. The
  info line is on every terminal of 3 rows or more, so the mode is never
  hidden.
- The plan in that slot changes the moment Hermes' todo tool changes it
  (Hermes' `todo.updated` has the HUD read again at once, instead of at its
  next poll two to eight seconds later), and a subtask keeps its place under
  its parent. Once every item is done it shows `✓ 3/3` until the turn ends,
  then leaves the panel, its final list written to the transcript above the
  turn's done line; a plan finished between turns leaves the same way, and
  one already finished when the session opens is not drawn. A plan with an
  item left stays. The active item's colour wave is the plan's only motion.
- The composer sits right under the output until the screen fills, then
  stays on the bottom rows. A fresh session shows it right under the banner,
  and after a turn it sits under the turn's last line with one blank row
  between, the spacer every block opens with. Until the screen is full, the
  plan or a question above the composer moves it down as it grows and up as
  it shrinks or closes, and the agent view under the info line follows it. The `/` and `@` menus open under the composer
  instead wherever they fit there short of the bottom rows, as in Claude
  Code, so the composer and the caret do not move; on the bottom rows, close
  to them, or before the TUI knows its place on the screen, they open above
  it. Output that brings the composer to the bottom rows while a menu is open
  under it takes the menu above it with that output, so closing the menu
  there moves nothing. Once the composer has reached the bottom
  rows it stays there: what grows above it scrolls the transcript up, and a
  list or question closing there does not pull it up, its rows staying blank
  above the composer until more is printed into them. A turn's end is the one
  exception: the `↳ you:` reminder, the blank row over it and the blank row
  over the plan go with the turn, so the composer rises by those rows (at most
  three, left blank under the footer) and the done line stays one blank row
  above it or the plan; the next turn's output takes it back down. The agent view under
  it takes at most a quarter of the screen, seven rows on a terminal of 28
  rows or more (so a one-row composer's input row is row 16 of 24 or 31 of
  40), raised only to show every running agent and never past a third of the
  screen; a DAG run's tree takes up to a third of the screen from the start
  (8 rows of 24, 13 of 40), and no more rows than the tree has. While
  a turn runs the view leaves the working row its place above the composer.
  As the view shrinks, the composer moves down, never up. On the bottom rows,
  once a turn ends, the view does not take the working row's place unless it
  needs more rows to show its agents, so the composer stays where it is and
  that place stays blank above it until output fills it. A resize or a
  redraw starts again under the output. Hidden while you pick from a list or
  search the history with Ctrl+R (the search's row stands where the
  composer was, the caret at the end of what you typed), it comes back as
  you left it.
  As it starts, the TUI scrolls what your terminal showed above its cursor
  (your shell, the launcher's warnings) off the screen, erases the
  terminal's scrollback (ED 3), as a full redraw (a resize, Ctrl+L,
  `/redraw`, switching or resuming a session) already does and as Hermes'
  own TUI does in its default alternate-screen mode (its main-screen native
  mode, `display.tui_native`, erases no scrollback), and opens on the top row of
  a clean screen, so scrolling up stops at the top of the session instead
  of reaching your shell's history. When you quit, the session stays above
  your shell's prompt, as any output does. A terminal that ignores ED 3
  keeps what was there one scroll up. iTerm2 asks first: while its
  app-wide Advanced setting "Prevent CSI 3 J from clearing scrollback
  history?" is unset, as it is by default, it shows "A control sequence
  attempted to clear scrollback history. Allow this in the future?" and
  keeps the history; once you choose Always Allow, the history is erased
  from the next launch or full redraw on (a resize or Ctrl+L, which
  already erase the scrollback, can show the same prompt). Inside
  tmux, ED 3 clears that pane's history, as `tmux clear-history` does. A
  launch that falls back to Hermes' own terminal leaves the screen as it
  was.
- A notice Hermes sends outside the transcript (the agent still starting, a
  credit warning, a provider that could not be reached) takes one row above
  the queued prompts, in its level's colour with a glyph. The next one
  replaces it, Hermes withdraws it, a timed one leaves when its time is up,
  and switching sessions drops it. A call Hermes refuses is said in words:
  under a command's echo, Hermes' own reason (`/undo` on an empty session:
  `No user messages to undo.`); otherwise what did not happen and why.
- What Hermes' background review saved to memory or skills after a turn
  is one dim row in the transcript, each skill named once with what it went
  through (`💾 skill <name> · created · wrote references/a.md · patched`),
  cut with `…` at the width rather than wrapped. While a
  `/goal` stands, the row above that notice says so as Hermes' own terminal
  does (`⊙ goal · 3/20 turns · <title>`, `⏳ goal parked · until 14:05 · …`,
  `⏸ goal paused · …`), until the goal is done or cleared. A mixture-of-agents
  turn keeps each reference model's answer as a collapsed row
  (`▸ ◇ Reference 1/3 — <model>`, its text in Ctrl+O's details), and the
  working row adds `MoA: refs 2/3`, then `MoA: aggregating…`.
- While a turn has delegated work, the agent view under the info line lists
  its subagents as Claude Code's agent list does: `● main`, then one row per
  agent, its mark (a spinner while it runs, `○` done, `✗` failed, `▪`
  interrupted, `◌` waiting for a worker), a short title (its goal up to the
  first field label such as `DELIVERABLE:` or the end of its first sentence,
  which an abbreviation such as `e.g.` does not end; a dag lane keeps its own
  label), and on the right the model it runs on, how long
  it has run, how many tools it called and how many output tokens it wrote
  (`deepseek-v4.1-flash · 12s · 3 tools · ↓1.2k`; `deepseek-v4.1-flash ·
  waiting 35s` while it waits, the model once a frame names it). The token
  count is read from the subagent's own Hermes session in state.db while it
  runs, so it grows a poll behind each model call, and is Hermes' own count
  once the agent finishes; there is no token part until there is a count,
  and as a row narrows it drops the token count first, then the tool count,
  then the time, and keeps the model longest; a row too narrow for the model
  shows the title alone. A subagent whose session
  Hermes' rotating compaction (`compression.in_place: false`) replaced with a
  new one counts every session it wrote in.
  The info line counts them (`2 agents · ↓ agents`; the count alone where
  the line is too narrow for both, or where Down would not open the list:
  while you type, while a question or a picker is open). During a DAG run the
  count is the run's running lanes (`1,204 agents`), and it goes once none
  runs or the run is over. The view stays
  while agents outlive the turn, each one's mark saying whether it still
  runs. With more agents than the view has rows, the running ones keep
  theirs and the rest are counted on its last row (`○ 3 done`, or `+4 more ·
  1 waiting · 3 done`); in two rows or fewer `● main` gives its row up
  first. While the conversation's delegation graph is a DAG run (a lane
  waits on another, or a lane delegates), the view is the run's folding tree
  instead: the graph's header (`DAG · <name> · N nodes · E edges · …`, the
  run's lanes and the edges between them, main and its dispatches not
  counted), a row per layer (`▾ layer 2 · 4 nodes · 2 running`; `28 of 640
  nodes` where the graph's node cap left some out, `▸ layer 4 · 0 of 161
  nodes` for a layer it left none of) with a blank row between
  two layers when either is open, and a row per node: a `▾`/`▸` fold
  triangle where something is under it, its state glyph (the spinner while
  it runs), its title, and its category, model, state and output tokens. The
  title is the node's label, followed by its prompt's first clause when the
  label is under 24 cells, cut at a word with `…` past 52 cells. The figures
  stand in columns two cells after the widest title, each as wide as its
  widest value; where the row is too narrow the tokens go first, then the
  category, then the model.
  Under an open node two `›` rows say what its child is doing: its latest
  call (`terminal(gh pr checkout 138300)`) and its latest other line, a
  thinking line, Hermes' progress line (the names of its last five calls) or
  its reply, whichever came last, never repeating the call above it. While
  a child waits on its model, Hermes sends its spinner text (`(°ロ°)
  pondering...`) as that child's thinking line, with nothing marking it as
  such, and the tree shows it as sent. A
  repair hangs under the node it repairs (`↻ repair 2 · …` in its second
  repair cycle), and the agents no node names close the tree as `other
  agents`. Running and failed nodes are open, and so is a node with one of
  them under it; the rest are shut. A tree taller than its rows shuts its
  quiet layers, then folds a busy layer's quiet nodes into one `▸ N more ·
  …` row, then shuts open nodes from the bottom (one over a running repair
  stays open). What still does not fit is cut: the shut all-done layers go
  first, so running and failed nodes keep the rows, then the rows from the
  bottom, and the last row counts what is cut (`… N more nodes · ↓ to
  browse`). A new turn keeps the open run's agents, so the rows under its
  nodes stay. Your folds last as long as the run: a new run, or another
  session, starts with none. `/dag` shows the
  graph with boxes. Once every lane has
  settled and the turn has ended, the tree is one line (`DAG · <name> · done
  5/6 · 1 failed`); while the turn still runs, it stays. On the screen's
  bottom rows the tree keeps the most rows it took this turn, blank under it
  where it shrank, so the rows between the transcript and the working row
  never open up mid-run.

  ![A dag run's folding tree under the OMH TUI composer: layer 1's accepted inventory shut, layer 2's two running groups open with each child's latest call and line under it, the failed group 3 with its error and the repair running beneath it, group 4 ready, and the verification waiting in layer 3](../assets/omh-tui-dag-tree.png)

  With no live subagent the view shows the HUD's agents block (`● main │ 3
  agents · 1 running`, then its rows). On a terminal under 6 rows or 20
  columns there is no view, and the info line keeps the count. Down on an empty composer
  gives the view's rows the keys as a list you pick from, as from a picker:
  the composer keeps its rules and says `↑↓ browsing · esc to type` while it
  is open, so nothing on the screen moves; the list scrolls when there are
  more agents than rows; and
  the info line says its keys (`↑↓ select
  · ⏎ log · x interrupt · s steer · esc back`). In a DAG run Down gives
  the keys to the tree instead, on its first running node, the same way:
  ↑↓ move over its rows, ← shuts the highlighted row (or, shut, goes to its
  parent), → opens it and Space flips it (an `N more` row gives way to
  the nodes it held), a fold you make stays, the rows scroll between `… N more nodes
  above` and `below`, and Enter, `x` and `s` act on the highlighted node's
  agent as they do in the list (`↑↓ select · ←/→ or space fold · ⏎ log · x
  interrupt · s steer · esc back`); on a layer's row, or a node no agent ran
  for, they do nothing. A click on a tree row highlights it, and on a node's
  row opens its agent's log. With fewer than three rows for the tree, Down
  opens the list instead. Esc, `q` or Ctrl+C closes the list or the tree,
  and so does Left in the list (in the tree Left shuts a row or goes to its
  parent, and never closes the tree); the composer comes back on its row as
  you left it; any other key does
  nothing while the list is open, so nothing typed there lands in the
  composer. Enter, or a click on its row,
  opens that agent's log on the alternate screen (its thinking lines, tool
  calls and reply, read-only, refreshed while it runs); Left and Right move
  between agents and q or Esc goes back. Two keys in the list act on the
  highlighted agent and nothing else does: `x` asks on the info line
  (`x again interrupts <agent> · any other key cancels`) and a second `x`
  interrupts it (`subagent.interrupt`); `s` makes the next line you send that
  agent's steer (`subagent.steer`), which Hermes hands it at its next tool
  call, with the info line saying so until you send it or press Esc (which
  keeps what you typed, as an ordinary draft). A steer
  Hermes does not take comes back to the composer, and so does one Hermes
  has not answered in 120 s, which is never sent again; its row says which,
  with Hermes' reason when it gave one. Its row reads as the main
  steer's does, naming the agent before the text (`↪ steer · <agent>:
  <text>`, then `↪ steer queued by Hermes · …`), and it and what `x` reports
  wait under the running call and are written at the next block boundary,
  so neither cuts that call off nor splits a reply.
- The OMH TUI asks the terminal for click reports only while the agent list
  is open, so during a turn the wheel scrolls and a drag selects as in any
  shell, and the agent view is reached with Down; nothing in it, and
  nothing on the info line, is clickable while the list is closed. While the list is open a plain drag no longer selects text in
  most terminals and the wheel does not scroll. To select anyway, hold Fn
  while dragging in Terminal.app (or turn off View → Allow Mouse Reporting),
  Option in iTerm2, Shift in most other terminals. Selection and the wheel
  come back as soon as the list closes, while a question is open, and while
  the window is being resized. While click reports are on, and for 0.5 s after they go off, an Esc pressed on
  its own acts after 0.3 s, the time a click report split by a slow
  connection has to arrive whole. Another key typed within that time ends
  the wait, and both keys act, except `[`, which is read as the rest of a
  sequence, as is `O` arriving together with the letter that ends F1 to F4,
  an arrow, Home or End. A key the terminal sends in the same burst as the
  Esc is Alt with that key, with click reports off too (tmux before 3.5
  holds an Esc for half a second and sends a key typed meanwhile that way):
  the Esc is lost and a character still types, while Enter and the arrows
  keep their Alt meaning, a new line and a word, and so do `b` and `f`,
  which move back and forward a word (readline's Alt+B and Alt+F, and what
  macOS Terminal.app sends for Option+← and Option+→). A report that starts later
  than 0.5 s after they went off, split by the connection right after its
  first byte or two, can still type its rest, and so can any report that
  takes more than 0.8 s to arrive whole.
  A click is read only where the OMH TUI can tell which row it landed on:
  once the session's output has reached the bottom of the screen, or after
  Ctrl+L. Until then it leaves the mouse to the terminal, and the keys still
  open the list and the logs.
- A view on the alternate screen (Ctrl+O, `/history`, `/logs`, `/dag`, an
  agent's log, the bot board, `/keys`) takes the mouse for itself, since that
  screen has no scrollback for the terminal to scroll: the wheel scrolls the
  page three lines a notch (on the bot board too, where the highlight stays
  on its row), a drag selects text (shown reversed) and copies it when you
  let go, without the rail a block hangs on or a reply's margin, a double
  click copies a word and a triple click a row, and a key or the wheel drops
  the selection; the wheel does nothing while you drag. A second click
  counts toward a double click only after a plain click on the same cell, so
  dragging again from where the last drag started selects again. The footer then says `✓ copied 694 chars to clipboard` for
  2 s. The copy goes out as OSC 52 to kitty, Ghostty, WezTerm and Alacritty,
  which honour it as they ship; on a Mac the OMH TUI runs on locally (no SSH),
  any other terminal gets it through `pbcopy`, and so does tmux once `tmux
  show-environment SSH_CONNECTION` says its last client did not attach over
  SSH. Elsewhere it
  goes out as OSC 52 with nothing to confirm it, and the footer says `⚠ copy
  sent (terminal may not support OSC 52)` (under tmux, that tmux passes it on
  only with `set-clipboard on`). On the main screen the terminal's own
  selection is the only one: the transcript is in its scrollback, and taking
  the mouse there would take the wheel and that scrollback away. Each rail is
  a painted cell holding a space, so what it copies there has no bar in it,
  only two leading spaces on each row (four on a reply's rows, with its
  margin), and the terminal shows no copy notice of its own.
- The composer takes a paste whole when the terminal brackets it, as most
  terminals do. A paste of more than 3 lines or 800 characters shows as one
  chip, `[Pasted text #1 +60 lines]` (or `· 1,204 chars` for one long line):
  the caret steps over it, Backspace, Delete and the line and word kills take
  it whole, and sending puts its text back where it stood. The transcript
  shows the chip. The chip's text is held in memory until you send it; once
  sent, the input history keeps the whole text, in this session and in
  Hermes' input history file (`$HERMES_HOME/.hermes_history`). A line that
  starts with `!` or `/` is a shell line or a command only when the composer
  shows it so: a chip whose text starts that way is sent as a prompt. A paste whose end marker never arrives ends after 0.5 s
  without input, as what arrived so far, and the keys after it are keys
  again, Ctrl+C included. Until that end marker arrives late, or for a second
  after the paste ended, a line break in what follows adds a line instead of
  sending, so the rest of a paste that only stalled stays text. Each read of
  several keys at once (how the rest of a paste arrives) starts the second
  again; keys typed one at a time do not, so an Enter typed within the second
  adds a line and the next one sends.
- When Hermes asks something (an approval, a clarify question, a sudo
  password), the question takes the slot until you answer. Nothing is answered
  for you: Esc or Ctrl+C declines. A question you answer by picking (an
  approval, a clarify question with choices) hides the composer while it is
  open, as Claude Code does: its choices stand where the composer was, each
  from a row of its own and wrapped under its number when long (so Hermes'
  `(Recommended)` at the end of the first one shows), the highlighted one
  marked `❯`. Nothing you type while it is open goes
  into your draft, and the draft comes back as you left it (its text, caret
  and paste chips) when the question closes, or when the last of several
  questions Hermes asked one after another does. While another question waits
  behind the open one, the open one says so after its first words
  (`· 1 more question waiting`). An approval offers deny,
  allow once, allow this session, always allow when Hermes offers it, and
  last no, and tell Hermes what to do instead, one per row in that order,
  with deny highlighted; allowing takes the arrows (Down or Right) and then
  Enter. Always allow is Hermes' own permanent
  allow, labelled with what it allows (`always allow recursive delete (Hermes
  saves it)`): Hermes saves that kind of command in its config
  (`command_allowlist`), so later ones run without asking, and Hermes does
  not offer it for a command its smart approval flagged. The last row
  denies at once, so the turn goes on, and opens the composer for what Hermes
  should do instead, labelled `↪ tell Hermes what to do instead · enter sends
  · esc cancels` on the info line: what you send goes into the running turn
  as a steer, the way Ctrl+Enter sends one (a steer Hermes does not take
  waits in the queue, and one it never answers comes back to the composer
  after 120 s), or as an ordinary prompt once the turn has ended, which
  waits behind a turn that started since (one you queued). The tell
  row of a later approval, picked while that composer is open, keeps it open
  with what you typed there. Esc there
  sends nothing more, since the deny already went: your draft comes back, and
  what you typed stays in this session's history. The
  highlight stops at either end, so Up then Enter still denies, no number
  picks a choice, `d` or `n` denies, and Enter on an untouched approval
  denies. Every deny (Esc, Ctrl+C, `d`, `n`, Enter on deny) also stops the
  running turn, as Esc does in Claude Code, which is what the info line's
  `esc denies and stops` says: the deny goes first, so the waiting tool ends
  denied, then the interrupt, and with no turn running only the deny goes,
  and the info line says `d or esc denies`.
  When the approval came from a subagent, that stops the session's whole
  running turn, not only the subagent. The tell row is the one deny that
  does not stop the turn; it redirects it. A clarify question numbers its choices: a digit, or Up and Down then
  Enter, picks one. One that takes several says `(choose one or more)` and
  puts a box before each choice: Space or its digit ticks the choice (`[x]`)
  or unticks it, Enter sends the ticked ones (the highlighted one alone when
  none is ticked), and an answer of your own joins the ticked ones. Its last row, `Other (type your answer)`, opens the
  composer as the field for an answer of your own, and so does typing any
  character that picks nothing, which becomes the answer's first character;
  Up or Down goes back to the list and keeps what you typed for that
  question, and Enter on an empty field does too; the next question's field
  starts empty. A sudo password, a secret and a clarify question
  without choices are typed into the composer. A long command wraps under its
  own indent and shows its first lines, and the line that names it wraps too.
  Whenever the slot cannot show the whole question (a long command, a long
  list, a short terminal) it says so, `… ctrl+o shows all` (under a command's
  first lines, `… +14 more lines · ctrl+o shows all`; `… ctrl+o` where the row
  is too narrow for more; beside a list cut short, on the side it is cut,
  `… +3 more choices, 1 ticked · ctrl+o shows all`, or an approval's
  `… more choices · ctrl+o shows all`), and Ctrl+O opens the
  whole question in the pager: it answers nothing, and q or Esc comes back to
  the question as you left it. A terminal too short for every row keeps the
  highlighted choice and, from 6 rows, a command's first row; one under 6 rows
  or 20 columns still shows a typed question's label above the composer.
  The question's keys are on the info line at every height.
  Keys pressed in the first moment after any question appears are ignored,
  Enter included (nothing is typed into an answer, cleared or sent), and so
  are those right after each next question of a batch, so typing that was
  meant for the composer, or for the question before, cannot answer it.
  The terminal bell rings once as any question opens (an approval, a clarify
  request however many questions it asks, a sudo password, a secret), so a terminal in the background can
  flag it, and a terminal that shows notifications gets one too, saying what
  Hermes asks (Hermes drops a clarify question nobody answers after its
  timeout, 300 s by default), and a turn that ran 10 s or more ends with the
  terminal's own notification: OSC 9 in iTerm2, WezTerm and Ghostty, OSC 777
  in foot and rxvt, the bell elsewhere (tmux among them, which flags the
  window); `OMH_TUI_BELL=0` keeps all of it quiet.
- While a turn runs, a light goes round the screen's edge, clockwise, once
  every four seconds, in the launch look's colours, and it is gone when the
  turn ends. To keep the edge free, the rows are drawn one column in from
  each side and the screen's last row stays blank, whether a turn runs or
  not. It shows with motion on, at truecolor, on a screen 20×8 or larger.
  `/glow off` turns it off and `/glow on` back on (`/glow` alone switches
  it); the choice is saved beside the theme, as `glow` in
  `<omh_home>/tui/theme.json`; `omh theme glow on|off` saves the same choice
  from the shell. `OMH_TUI_GLOW=0` holds it off in one terminal whatever is
  saved.
- Each tool call is a block of its own on a rail in its state's
  colour, with a blank row between two calls and no header over a turn's
  calls: its state's mark (below), its name, and what it ran on (a path, a
  command, a query) in parentheses, cut with `…` where the row is too narrow
  (`● terminal(rm -rf ./tmp-cache)  1.9s`). Under it (`  ⎿  `) it shows the first three lines of what the tool
  printed and counts the rest (`… +5 lines · ctrl+o shows all`). A read says
  in one line what it read instead: `Read 715 lines` for
  `read_file`, `12 matches` for
  `search_files` (`3 files` when it listed files, `50+ matches` when Hermes
  stopped counting, and Hermes' warning on the line under it when it gave
  one, such as why nothing matched). An `omh_memory` recall that found
  records lists them from its own result, a line each, type then summary
  (`decision  rotate refresh tokens per session`), so a found recall prints
  your memory's summaries into the local transcript; as the call lands, one
  band of the `dag-ulw` aura sweeps those lines once, where the composer's
  aura moves (truecolor, motion on), and in scrollback they are plain.
  Loading skills and reading tool details
  (`skill_view`, `tool_describe`) are plumbing: a run of them is one row,
  `● Loaded 4 skills + tool details · github-development-workflows, dag-ulw,
  hermes-agent, omh-routing/skill-common-rail.md  2.8s`, and any other call
  ends the run. A failed one keeps a row of its own with its error, and
  Ctrl+O unfolds the run, each load saying what it loaded (`loaded skill
  omh-docs`, `loaded references/api.md from skill omh-docs` for a file in
  it). A shell call whose heredoc feeds an interpreter its script
  (`python3 - <<'PY'`, `uv run python - <<'PY'`, `bash <<EOF`) names the
  interpreter and counts the script's lines and the commands around it
  (`terminal(python3 script · 23 lines)`), one a line: another heredoc's
  body, a comment and a `\` continuation add none; any other command fed a heredoc
  (`cat > a.py <<'EOF'`, `git commit -F - <<'MSG'`) shows its own first
  line, and Ctrl+O shows the command. A failed call (a red `✗` on a red rail) shows its error's first line,
  or, when it failed by its exit code alone (a test
  run, say), the last three lines it printed, under the
  count of the lines above them. An edit's diff hangs under the same `⎿`, and a long diff counts
  its rest the same way. A resumed session's earlier calls (`omh --resume`,
  `/resume`, a switch) are drawn the same way, a blank row between two,
  with a grey `●` on a grey rail, since Hermes' record of them keeps no
  outcome, and an edit's diff under it where Hermes kept the one it showed.
  Ctrl+O opens the whole transcript with every detail
  (thinking, tool output, whole diffs) in the pager, at its end.
- While a turn runs, the working row reads as Claude Code's does,
  `✶ Synthesizing… (1m 24s · ↓4.2k tokens · thinking with high effort · esc
  to interrupt)`: a glyph that turns, what Hermes says it is doing as a verb
  (its kaomoji and dots left out, `Working…` while it says nothing; a notice
  such as `No response from provider in 120s — reconnecting…` or `Retrying
  in 5.0s (attempt 1/3)…` keeps its words, cut at the edge), the
  time, the tokens the turn has written so far, and the reasoning effort when
  the session reports one (a row too narrow for all of it leaves out the
  effort first, then the tokens, then the time, then `esc to interrupt`,
  each one whole rather than cut). The tokens count up as the reply, the
  reasoning (when Hermes' `display.show_reasoning` sends it) and each tool
  call's arguments arrive, about four characters a token and one per CJK
  character, and move to Hermes' own count each time one of its usage
  reports arrives; the number never goes back during a turn, and the done
  line below carries Hermes' count. On a terminal 16 rows tall or more a tip sits
  under it, one a turn, each naming a key (`⎿  Tip: ctrl+o shows the whole
  transcript`). Once you interrupt it (Esc or Ctrl+C on an empty composer)
  it reads `✻ interrupting… (12s)` until Hermes has stopped the turn. What you queued behind that turn is not sent then:
  it comes back into the composer, as Claude Code does it, joined in order;
  a queued `!` line, which is never joined to a prompt, and what follows it
  stay queued (`held · ↑ edit`) until you send your next
  prompt or take them back with Up, and so does the whole queue if you typed
  something while the turn was stopping. Each turn ends with a dim line,
  `✻ 34s · 3 tools · ↓1.2k`, under the reply's words (a line too narrow for
  it drops the tokens, then the tools, then the wait, each whole, and keeps
  the time). While a question Hermes asked
  waits on you, the working row reads `? waiting on you (11s)` instead, its
  one clock counting that wait (the info line's OMH count of running tool
  calls, `1 tool · 9s`, drops its seconds meanwhile and leaves once the
  turn ends), and a tool's time on its row leaves the wait
  out, so a command you took 20 s to allow shows the 2 s it ran (a call Hermes
  ran beside it, which the question did not hold up, keeps its whole time). The done
  line keeps the turn's whole time and names the wait beside it,
  `✻ 30s (27s waiting on you) · 1 tool`, so it still matches the clock you
  sat through. The terminal's title names the session (Hermes
  titles it after its first turn) and whether it is idle, running or waiting
  on you; on exit the title you had comes back where the terminal keeps a
  title stack.
- Motion and colour follow one rule set, so scrollback reads at a glance:
  - Each block hangs on a continuous rail with no fill behind it, one cell
    painted in the rail's colour that holds a space, so selecting the text
    in the terminal copies no bar with it (only the two leading spaces;
    with `NO_COLOR` set only a reply's and a call's rail is painted, so your
    prompt is told apart by its `❯` and no bar): grey
    for your prompt, the theme's accent for what Hermes said (which opens
    with a header row, `⚚ Hermes · <model>`, bold in the rail's colour and
    the model the reply was written under muted), and a tool call's state colour for
    the call. The accent is left on the banner's title and that rail only;
    the rest of the chrome (rules, marks, hints, a call's arguments and what
    it printed) is neutral grey, and words are the brightest text.
  - A call's name is bold in its tool family's colour: skills and tool
    plumbing orchid, shell amber, files peach, web lime, delegation and the
    dag magenta, and a tool in none of them the text colour. Each reads at
    4.5:1 on a light and on a dark terminal, and none is a state colour.
  - A tool call's mark and rail say its state as the dag view's boxes do,
    each state in its own colour and its own glyph so colour is never the
    only signal: a blue `○` while it runs, pulsing between the blue and dim every 0.5 s
    from its own start (parallel calls pulse on their own; the rail holds
    still), a green `●` once done, a red `✗` when it failed or was denied,
    with the lines under a failure saying why: the error's
    first line, the denial's words (`denied` when the result gives none), or,
    for a command that failed by its exit code alone, the last lines it
    printed. The same running blue is the working row's glyph, the agent
    view's spinners and `● main`, and a running lane's dot and status in
    the dag tree; nothing that is not running is drawn in it (a list
    bullet, a diff hunk, a key, a question's bar are grey or bold).
    `▪` marks a call that was cut off and
    `◌` one still being written (a call Hermes never starts, such as a streamed
    attempt it discards and retries, leaves no row and is not counted in the
    turn's done line). Only the live region at the bottom
    moves; what reaches scrollback is the settled mark, never a frame of a
    pulse.
  - The working row's glyph turns (`· ✢ ✳ ✶ ✻ ✽`) and a highlight sweeps
    across its verb, beside the elapsed time and the tokens written.
  - Your prompt reads as in Claude Code, the composer's dim `❯` and dim text with no
    band behind it, on a grey rail; a prompt the queue sent says `⧗ from queue`. A command
    you run is echoed the same way, on the same rail (`❯ /model`), so a
    bare `❯` on the left edge is only ever the composer.
  - A steer shows as `↪ steer · <text>` under what is running until Hermes
    answers, then becomes `↪ steer queued by Hermes · <text>`, or the amber
    refusal, at the next boundary in the transcript (see below).
  - Each turn closes with its done line, dim and with no rule after it
    (`✻ 34s · 3 tools · ↓1.2k`), so the start of the next one is easy to
    find when you scroll back.
  - Green and red mark outcomes as full-row bands (each row's background is
    erased to the right edge, so a copy carries no trailing spaces). The answer you gave an approval is written
    under the call it was about, as the first row under its own: allowed
    (`⎿  ✓ allowed once · <command>`) on a light green band, denied
    (`⎿  ✗ denied · <command>`) on a light red one. A question names no call,
    so the answer goes under the last call still running (for a clarify
    question, the last running `clarify`); with none running, such as a
    subagent's question after its turn ended, it is a row of its own. The
    answer you gave any other question goes the same way: the label you picked or what you
    typed (`✓ red · Which colour?`, ticked labels joined with commas, empty
    items of a multi-select answer left out, as Hermes leaves them out), and
    for a sudo password or a secret only `✓ answered · sudo password` or
    `✗ declined · sudo password`, never the value; a question you cancelled,
    sent empty (a multi-select answer with no item left too), or Hermes
    withdrew says so in red (`✗ cancelled · <question>`,
    `✗ skipped`, `✗ timed out`, `✗ interrupted`, or `✗ withdrawn (<Hermes'
    reason>)`), and the `clarify` call it was about has a red `✗` too, with
    `cancelled`, `timed out` or `not delivered` under it when no such answer
    of yours is under it already to say so. Once a call has ended failed or
    denied, its own `✗` is the one mark: the red answer rows under it keep
    their words and drop theirs (`⎿  denied · <command>`). An error notice and a
    command's error line (for a failed `!` command, with what it printed
    above it) are on the light red band too. A tool call itself has no
    band: its rail and its mark say how it ended, and a denied call shows one
    mark, a failure's red `✗`. Warnings stay amber, with no band. The bands follow
    the theme and the background: light tints on a light terminal, dark
    ones on a dark terminal, with words on them at 4.5:1 and marks at 3:1
    against the band; with no background reported (by the terminal or its
    `COLORFGBG`) and none named with `/theme light` or `/theme dark`, no band
    is painted. Only
    settled rows carry bands, never one that moves. Every notice still
    reads apart without colour, by its glyph or its words; a tool call's
    state is its mark's shape and colour, with a failure's or a
    denial's line under it. Diff lines keep their own bands.
  - `OMH_TUI_REDUCED_MOTION=1`, or `NO_COLOR`, stops the motion: no pulse
    and no sweep, every spinner holds its first frame, and while a turn runs
    the screen repaints once a second for the elapsed time instead of ten
    times.
  - `NO_COLOR` set to anything but an empty value (no-color.org) also draws
    the whole TUI without colour: the transcript, the composer and info
    line, the agent view and the dag tree, the pager, the pickers, the diff,
    the logo, and the rows on a band. Bold, dim, italic, underline and
    reverse stay. The bands are not drawn: a diff line keeps its `+` or `-`,
    and an answer keeps its words. The highlighted row of a menu or a list
    and the pager's footer bar are reversed, and every state keeps its
    glyph.
- Images: drag an image file onto the terminal, press Ctrl+V for an image on
  the clipboard, or type `/image <path>`. Each one is a token at the caret,
  `[Image #1]`, in the text you type around it (`[Image #1] like this`).
  Images are numbered upward through the TUI run, as Claude Code numbers
  them, past any number a resumed session already holds. The OMH TUI keeps
  the image's bytes in memory, and Hermes holds the image only while the
  prompt it goes with is sent, so the image belongs to its token: whatever
  deletes the token (Backspace into it, Cmd+Backspace, Ctrl+W, Ctrl+U,
  Ctrl+K, Ctrl+C, Esc Esc) removes the image, and an undo puts both back.
  The prompt keeps the `[Image #N]` labels in its text so the model can name
  them, and the transcript lists under it each image Hermes accepted for it
  (`⎿  [Image #1]`). A `!` line or a command that sends no prompt gives its
  tokens back to the composer. Enter right after a paste or a drop waits for
  Hermes to answer it, under `waiting for the image…`, and the prompt goes
  with that image (a one-line text paste joins it the same way); Esc or
  Ctrl+C meanwhile gives the prompt back. Typing `[Image #1]`
  yourself attaches nothing, and a prompt recalled from history is plain
  text. Dropping a file
  that is not an image types Hermes' reference to it instead.
- A line that starts with `!` is a shell command: while the composer holds
  one, its `❯` mark turns the shell family's amber and the info line says
  `! shell (not sent to the model)`. Sending it runs it through Hermes'
  `shell.exec` (Hermes' own limit of 30 s, its refusal of dangerous commands,
  and its redaction of what the command printed) and shows `❯ !command` on the rail
  with what it printed (its stdout, then its stderr, in the same colour) and
  its exit code when that is not 0 (`exit 0` when it printed nothing; a
  failure's lines are red on the red band with that exit line), or
  Hermes' reason for refusing it. Neither the command nor its output goes to the
  model. During a turn it waits in the queue and runs when the turn ends; a
  prompt queued behind it waits for its output. Only a line you sent with
  `!` waits as a shell line: a steer Hermes refused, or a message a command
  built, goes to the model even when its text starts with `!`, and ↑ takes
  a queued `!` line back on its own, never joined to a prompt.
- Esc twice (within 0.8 s) on an empty composer between turns, or `/rewind`,
  lists this session's prompts, newest first; the one you take comes back
  into the composer, and the info line says that sending it replaces that
  prompt and everything after it. Send it (edited or not) and Hermes drops
  that prompt and what followed (`prompt.submit` with
  `truncate_before_row_id` and `confirm_truncate`), and the screen is redrawn
  from the cut with your prompt under it; Esc instead cancels and empties the
  composer. A rewind goes as a plain prompt, never through plan mode. A
  slash command you send instead still runs: one that sends a prompt (a
  skill, `/plan`, `/steer <text>`) sends it in place of the picked prompt,
  the same way, and one that only prints (`/help`, `/usage`) leaves the
  rewind picked for the next prompt you send. `/retry` and `/undo` cancel
  the rewind, even one picked while they were out, and say so, since Hermes
  takes the last turn back itself: `/retry` resends as it does without one,
  and the prompt `/undo` puts in the composer goes plain. If Hermes refuses a
  rewind, the screen goes back to how it was before you sent, and is then
  redrawn from the history Hermes sends, as Hermes still has the session; if
  Hermes does not send that history, a notice says so and the
  screen stays as it was before you sent. A prompt you queued behind the
  rewind goes once that is settled.
  Esc twice with text clears it, keeping it in this session's input history
  (not in Hermes' history file, since it was never sent).
- `/sessions` (also `/resume`, `/switch`, `/session`) lists your stored
  sessions in the slot, most recently active first: the one you are in
  heads the list under `Current` (`this session` until it has a title),
  and the rest sit under a heading for the day each started (Today,
  Yesterday, Previous 7 days, Earlier), each session's age and message
  count in columns of their own. Type to filter (what you type shows on
  the list's last row, where the composer was, with the caret, and only the
  headings with a match stay), Up/Down or PageUp/PageDown to move from
  session to session, Enter to switch, Esc to close. Each alias runs
  exactly as `/sessions` does, and the `/` menu offers `/resume` under its
  own name once what you type starts it: `/res` and `/resu` complete to
  `/resume`.
  `/sessions <id or exact title>` (or `/resume <id or exact title>`)
  switches directly. A title Hermes' shared gateway does not resolve as an
  id is looked up by its exact title over all your sessions, then among
  the listed ones ignoring case: one session with that title is opened,
  and when several (titles that differ only in case) or none have it the
  picker opens filtered by what you typed and says how many matched. The
  screen is redrawn as
  the session you picked, with its earlier turns; the one you left closes only
  after the new one opened, so a session that cannot be opened (for example
  one another process holds) leaves you where you were.

Keys (`?` on an empty composer, or `/keys`, shows this list in the TUI; q or
Esc closes it):

| Key | Does |
| --- | --- |
| Enter | Sends the composer |
| `\` then Enter, Alt+Enter, Shift+Enter, Ctrl+J | Adds a line |
| Ctrl+Enter | While a turn runs, sends the composer's text into it now as a steer (`/steer <text>` too); idle, sends as Enter does |
| Ctrl+Enter, Ctrl+J | While a turn runs, on an empty composer, send the oldest queued prompt into it now as a steer; the row under the queue names the key (Ctrl+J where the terminal has not shown it tells Ctrl+Enter from Enter). A queued `!` line, skill prompt or plan prompt waits its turn |
| Tab | Completes a slash command, or the `@` reference being typed; on an open menu, Enter takes the highlighted row too, and sends a command already typed in full |
| Shift+Tab | Cycles the input mode: normal, accept all (Hermes asks no approvals in this session), plan (prompts go as /plan); while Hermes itself has approvals off, turns plan on and off |
| Ctrl+T | Steps the reasoning effort: low, medium, high, xhigh, max; the info line shows it as effort medium |
| `@` | Starts a file or folder reference; Hermes offers matches above the composer |
| `!` | At the start of a line, makes it a shell command Hermes runs when you send it (30 s at most); it and its output are not sent to the model |
| `?` | On an empty composer, shows this list; `/keys` does too |
| ↑ / ↓ | Move between the composer's rows, walk the input history at its first and last row (earlier sessions' too, shared with `hermes --tui`), or move through an open completion menu |
| Ctrl+R | Searches the input history; Ctrl+R again finds an older match, Enter puts it in the composer, Esc leaves the composer as it was |
| Ctrl+X | Opens the `/sessions` picker |
| Ctrl+S | Opens the bot board, as `/bots` does: this machine's Hermes profiles, their gateways and sessions, read-only |
| Ctrl+P | Folds the plan above the composer to its header and the item it is on, or expands it again, while a turn runs or between turns; the header says which on its right |
| ↑ | On an empty composer with prompts queued, takes them back into the composer to edit; a queued shell line comes back on its own |
| ↓ | On an empty composer while the agent view under the info line shows subagents, gives its rows the keys as the agent list; in a DAG run, to its folding tree |
| ← / → | Move by a character; with Ctrl or Alt, by a word (Alt+B and Alt+F too) |
| Home / End, Ctrl+A / Ctrl+E | Go to the start or the end of the line |
| Backspace / Delete | Delete a character, or a paste chip or an `[Image #N]` token whole; deleting a token removes its image |
| Ctrl+W, Alt+Backspace, Ctrl+Backspace | Deletes the word before the caret (Ctrl+Backspace where the terminal reports it apart from Backspace) |
| Ctrl+U / Ctrl+K | Delete to the start or the end of the line |
| Ctrl+_ / Ctrl+Y | Undo or redo an edit in the composer (Ctrl+_ is what Ctrl+- and Ctrl+/ send on most terminals); a run of typed characters is one edit |
| Esc | Closes the `/` or `@` menu; on an empty composer, interrupts a running turn (the activity row shows how long it has run, then `interrupting…`, and what you queued comes back to the composer unsent); cancels a rewind you picked; cancels an agent steer you picked and keeps what you typed; after an approval's tell row, sends nothing more and brings your draft back |
| Esc Esc | With text, clears it and keeps it in this session's history; on an empty composer between turns, lists your prompts to rewind to (`/rewind` does too) |
| Ctrl+V | Attaches the clipboard image as an `[Image #N]` token at the caret |
| Ctrl+O | Opens the whole transcript with every detail (thinking, tool output, whole diffs) at its end, or, while Hermes asks something, the whole question (it answers nothing); q leaves it |
| Ctrl+L | Redraws the screen |
| Ctrl+Z | Suspends the OMH TUI to the shell, as Ctrl+Z does in any terminal program (Hermes stops with it); fg brings it back |
| Ctrl+C | Clears the composer, else interrupts a running turn; a second press within 2 s exits, mid-turn too; a prompt held for its pasted image comes back to the composer |
| Ctrl+D | On an empty composer, exits; with text, deletes the character ahead |
| ↑ / ↓ or ← / → then Enter | On an approval, highlight allow once, allow this session or (when Hermes offers it) always allow, and allow it, or the last row to deny and tell Hermes what to do instead; Enter alone denies and stops the running turn |
| `d`, `n` | On an approval, deny and stop the running turn |
| 1 to 9 | On a clarify question's list, pick that choice, or the last number opens the field for your own answer; ↑ / ↓ then Enter picks too, and any other character starts your own answer |
| Space | On a clarify question that takes several choices, ticks or unticks the highlighted one; Enter sends the ticked ones, or the highlighted one when none is ticked, and a digit ticks its choice |
| Esc, Ctrl+C | On a question Hermes asked, decline it (an approval is denied and the running turn stops); Ctrl+C first clears an answer being typed |
| ↑ / ↓, PageUp / PageDown, Enter, Esc | In the `/sessions`, `/rewind` or `/model` list, move, take the highlighted row (switch to that session, put that prompt in the composer to send again, or switch this session to that model), or close it; typing filters the list |
| ↑ / ↓, Enter, Esc, ←, q, Ctrl+C | In the agent list, move, open the highlighted agent's log (on main, only leave), or go back; any other key does nothing there |
| x, s | In the agent list, on an agent: x twice interrupts it; s steers it with the next line you send (Esc cancels) |
| ↑ / ↓ or a click, Enter, Esc | In the `/theme` picker, preview a launch look (spectrum, violet, gold, graphite, sakura, moonlit, aurora, ember) on the logo, the card and the chrome, keep it, or put the one in use back; `/theme <look>` keeps one at once |
| Click | On a row of the agent list, opens that agent's log (on main, only leaves the list) |
| ← / →, q or Esc | In an agent's log, show the agent before or after, or go back; the pager's keys scroll it |
| Tab / n, Shift+Tab / p, Space / Enter, d | In `/dag`, highlight the next or the previous box, fold or unfold the highlighted one, or show or hide Node details; ↑ / ↓, PageUp / PageDown and g / G scroll, q or Esc leaves |
| ↑ / ↓, Enter or →, ← or Esc or q, r | On the bot board, move, open a profile's sessions or a session's last messages, go back (on the profiles, close the board), or read it again now; it reads again every 5 s by itself |
| j / k, Space / b, g / G, q or Esc | In a pager (`/history`, `/logs`, an agent's log, this list), move a line, a page, or to either end, or leave |
| Drag, double click, triple click, wheel | In a pager (`/dag` and the bot board too), select text and copy it when you let go (without the rails), copy a word, copy a row, or scroll three lines; the footer says what the copy did |

Ctrl+Enter and Shift+Enter reach the OMH TUI as keys of their own only where
the terminal reports them. On start it asks iTerm2, kitty, WezTerm, tmux, VS
Code's terminal and Windows Terminal (under WSL) for the kitty keyboard
protocol and xterm modifyOtherKeys, and Ghostty for modifyOtherKeys only: the
terminals Hermes' own TUI asks, recognised as Hermes recognises them, from
`TERM_PROGRAM`, `TERM`, `TMUX`, `KITTY_WINDOW_ID` or `WT_SESSION`. The
start-up query then asks every terminal which kitty flags are on (`CSI ? u`).
A terminal it did not ask that answers speaks the protocol, so it is asked
then (Otty with its `kitty-keyboard` setting on is one; never Ghostty); an
answer that says the request took names Ctrl+Enter from the first frame. A
terminal the environment does not name (over SSH, where `TERM_PROGRAM`
rarely arrives) is also asked its name (XTVERSION) and is asked only when
that names kitty, WezTerm, foot, Alacritty, Rio or Otty, since an unnamed
answer may be Ghostty's. Both reports are switched off on exit, a crash,
SIGTERM and SIGHUP included (a `kill -9` leaves them on, as it leaves raw
mode), and asked for again after Ctrl+Z and `fg`. Elsewhere, Terminal.app
among them, both keys send what Enter sends, so there Ctrl+J is the send-now
key (every terminal sends it as a line feed, apart from Enter's carriage
return); anywhere else, `\` then Enter, Alt+Enter or Ctrl+J adds a
line; while a draft spans lines there (typed, or pasted), the info line
says so (`⏎ sends · \⏎, alt+⏎ or ctrl+j adds a line`). A terminal on the
list can ignore the request too (tmux with `extended-keys off`), so the row
under the queued prompts names `ctrl+j` until the terminal shows it took the
request (its answer to the query, or a first key in one of those reports),
and `ctrl+enter` from then on. `OMH_TUI_KEYBOARD=legacy` stops the request
and the query on any terminal.

Shift+Tab cycles three input modes, and the info line shows the one that is
on. Accept all turns off Hermes' approval prompts for that
session only. The OMH TUI sets Hermes' per-session switch, the one Shift+Tab
sets in Hermes' own terminal, and never `approvals.mode`; it shows the mode
only once Hermes confirms the switch for this session (or, when Hermes confirms
neither a switch on nor the switch back off after it, shows accept all, since
approvals may then be off), and switches it back off when you leave the mode,
and before it leaves the session (`/new`, a switch, `/quit`, any exit), since
Hermes keeps it through closing a session a messaging gateway started. A new
or resumed session starts from what Hermes
reports for it, and when Hermes reports approvals off for its own reasons
(`approvals.mode` is off, it was started with `--yolo`, or `/yolo` turned them
off) the info line shows accept all as well. Those approvals are not the OMH
TUI's to turn back on: Shift+Tab then sends nothing and turns plan mode on and
off beside accept all, and the transcript says so once per session. In plan
mode each prompt you send goes to Hermes as `/plan <text>`, its prompt for a
written plan instead of the work; that is an
instruction to the model, not a restriction on its tools. An answer to a
question Hermes asked is sent as typed in every mode.

Ctrl+T steps this session's reasoning effort, and `/effort <level>` sets any
level Hermes takes (`none`, `minimal` and `ultra` as well). The info line shows
the session's level on its right, as `effort medium`, and Ctrl+T steps on from
the level shown. Hermes names it once it has built the session's agent, which
it starts right after the session opens; until then the line shows the level
Hermes' config sets (`agent.reasoning_effort`, read from the settings the TUI
reads at launch and after a gateway restart, and shown again in each session
`/new` or a switch opens), which a resumed session that ran with a level of
its own replaces once Hermes names that one. Where none is configured, so
the provider's own default applies, it says `effort default` and the
first Ctrl+T sets `low`; where per-model overrides (`agent.reasoning_overrides`) may apply,
it says `ctrl+t effort` until the session reports one. A level you set
shows once Hermes confirms it; a level Hermes refuses leaves the line as it
was and says so.

A steer adds what you typed to the turn that is running, without interrupting
it: Hermes reads it after its next tool call, or, while it is compressing the
context, queues it and sends it as the next prompt once compression is done.
Hermes gives the same answer for both, so the transcript notes
`↪ steer queued by Hermes` for either. Until Hermes answers, the steer shows
as `↪ steer · <text>` under what is running, and its row is written into the
transcript at the next boundary after the answer, never between calls that
are still running or inside a streaming reply. If Hermes does not take the steer
while the turn still runs (an agent still starting, or one that takes no
steer), the text joins the OMH TUI's own queue (`⧗`) and goes when the turn
ends, whatever `display.busy_input_mode` says, so it never interrupts the
turn; if the turn had already ended, it goes as an ordinary prompt. Either
way the steer's row says so in amber (`⧗ queued — Hermes refused the steer
(<why>) · <text>`). A steer Hermes has not answered in 120 s is never sent or
queued again, since Hermes may have taken it: its text comes back to the
composer, after what you are typing (while Hermes asks you something, after
the draft you get back when the question closes, never into your answer),
and its row says so (`⧗ back in the composer — Hermes did not answer the
steer in 120 s · <text>`). An agent's steer comes back to the composer the
same way. If you
left the session (`/new`, a switch) before Hermes answered, the text comes
back to the composer and is not sent to the session you are in, and a notice
says so; for an agent's steer it names the agent and the session you left. The OMH TUI
steers only with text you typed and sent this way: a queued prompt is never
turned into a steer.

A slash command you run is echoed in the transcript as `❯ /name arg` on the prompt's rail (but
`/steer`, whose own row is its echo, and a bare `/sessions`, `/rewind`,
`/model`, `/keys`, `/history`, `/logs`, `/dag`, `/bots` or `/redraw`, which only open a picker
or a pager, or repaint, and print nothing to attribute), and what it prints stays there, under it after `⎿`, in the terminal's scrollback
(each command's output under its own echo, also when you send a second command before the first answers).
A skill command (`/<skill> <request>`) is one row: its echo gives way to the row of the prompt the skill sends
once Hermes answers. That row shows the command, as Hermes names it for the turn (the row a resumed session shows)
or else as you typed it, not the expanded skill prompt that is sent; an echo already written to the scrollback
before Hermes answered stays, with the prompt's row under it.
Typed during a turn, the echo and its output wait under what is running and are written after it, as a
steer is, so a command never cuts off a running tool call or splits a reply; one Hermes has not finished
answering when the turn ends is written above that turn's done line with what it printed so far, and
what it prints later goes under a repeat of its echo. In the transcript, a long output shows its
first 12 rows and a count of the rest
(`… +K rows · ctrl+o shows all`, rows at that width), and Ctrl+O or `/history` shows all of it. Nothing a
command prints opens a pager; a pager opens only when you ask for one
(`/history`, `/keys`, `/logs`, `/dag`, `/bots`, an agent's log), and output that arrives while
one is open is in the transcript when you leave it.

Slash commands the OMH TUI runs itself: `/help` (which also lists, in Hermes'
words, any skill whose name a built-in command takes, such as Hermes' own
`plan`, and which runs as `/skill <name>`; that is no notice at the start),
`/keys`, `/quit`, `/new`,
`/sessions`, `/redraw`, `/history` (an in-memory pager over this session),
`/details` (show or hide thinking and tool detail on the live block),
`/queue`, `/steer <text>`, `/effort <level>`, `/logs` (the gateway's recent
stderr, kept in memory only), `/dag` (the session's delegation graph as
boxes, full screen in the pager and redrawn from the HUD's newest read: Tab
and Shift+Tab move the highlight, Space folds a box, d shows or hides Node
details; it sends nothing anywhere; q or Esc closes it), `/bots` (the bot
board, also Ctrl+S, described below), `/copy`, `/image`,
`/paste` (the clipboard
image), `/theme`, `/glow`, `/omh-model`, `/rewind`, `/todos` (the session's whole
plan), `/model` (alone, a picker of the models Hermes offers this session,
from Hermes' `model.options`, opened on the session's model, marked `●`, which
comes first when no provider lists it, and with the highlight's place in the
header, `Model (12/162)`, once the list scrolls; the one you pick is sent as Hermes' own
`/model <name> --provider <slug> --session`, so it lasts for this session;
`/model <name>` goes to Hermes as typed), `/export` (Hermes' export writes a
profile archive, not the transcript, so the first `/export` says so and the
next one runs it), and `/reload-skills` (Hermes re-scans its
skills for this session and the TUI reads its command list again, so a skill
installed since the start, by `omh update` or `/skills install`, runs as
`/<name>` without a restart). Claude Code's `/cost`, `/permissions` and
`/compact` run Hermes' `/usage`, `/approvals` and `/compress` (`here [N]`, a
focus topic, or `--preview`; Hermes refuses a compression while a turn runs,
and the TUI says to run it again once the turn ends). Hermes' shared gateway,
which a Hermes from v0.22 runs, does not take `/compress`, `/branch`,
`/retry`, `/undo`, `/stop`, `/bg`, `/btw`, `/rollback`, `/reload`,
`/reload-mcp`, `/tools`, bare `/plugins` or `/config` as a typed command. The
TUI runs each one through the gateway call Hermes' own Ink TUI uses for it,
and `/branch` then opens the new session. The shared gateway answers one call
at a time, so while a `/compress` this TUI sent runs, a command, prompt or
interrupt sent meanwhile waits until the compression ends; the TUI waits for
its answer that long, at most 780 s in all.
Commands that only Hermes' classic CLI runs (`/handoff`, `/worktree`,
`/snapshot`, `/import`, `/hatch`, `/palette`) are left out of completion, and
`/help` names them on one line. Typed, they go to Hermes, which says where to
run each one.
Commands whose screen exists only in Hermes' own terminal (`/voice`, `/pet`,
`/agents`, `/subscription`, `/save`, `/prompt`, ...) say so and name
`hermes --tui`. Everything else goes to Hermes as it would from Hermes'
terminal, except that bare `/skills`, whose screen there is an overlay,
prints the help of Hermes' skills command here instead of opening the skills
hub. The command list is read again for each session
the TUI opens, so a project's own skills are listed in its workspace, and
completion also matches a part of a name: `/uml` finds `/omh-codebase-uml`.

The bot board (Ctrl+S or `/bots`) shows this machine's Hermes bots, full
screen, and changes nothing. Every region on it is a rounded box, in the
launch card's style, its columns divided by lines that meet the edges in
joints. Its first page opens with a box of what every profile adds up to
(gateways up, agents running, and the active sessions' tokens and cost), then
lists the Hermes home the TUI runs under and every named profile beside it
(`<root>/profiles/<name>/`), each in a full-width card, one to a row, every
card's columns lined up with the next. A card's top edge carries
its gateway's state as a coloured mark, the bot's name (with the display name
Hermes keeps in `profile.yaml`, when it set one) and, on the right, the running
gateway's uptime, agents and resident memory; its bottom edge carries what the
gateway says when it is not plainly running, each platform as a chip coloured
by its state (`!` when it needs attention or failed, `○` when the gateway that
recorded it has since stopped or restarted) and a restart Hermes was asked
for. Inside, at the left, is a small face drawn from the bot's name alone,
the same on every run, then the bot's fields, in two columns where the
terminal is about 117 columns or wider and stacked in one below that:
`model`, the default
model its `config.yaml` names (and the model its newest session ran, when that
differs); `now`, its newest session but delegated children, its title cut to
fit and its source and age at the right; `24 h`, a sparkline of the active sessions' tokens by the hour each
was last active, how many were active, and how many are stored; `tokens`,
their input, output and cache-read tokens; `cost`; `memory` and `user`, Hermes'
`MEMORY.md` and `USER.md` as gauges against the limits its `config.yaml` sets
(green below 70%, amber to 90%, red past it); and `OMH`, the record count of
the OMH store its `config.yaml` names. The highlighted bot's card takes the
theme's accent colour. Tokens and cost are each
session's lifetime totals, since Hermes records no time per call, and the board
labels them `lifetime` wherever it shows them; a cost
appears only where Hermes priced it (`~` marks an estimate); sessions it did
not price are counted as unpriced, never as $0. A store, config or memory
file it cannot read is named as such, and a store without the token columns
shows neither tokens nor a sparkline. A narrow terminal gives up the least
important figures first (the top edge's figures, then the last chips and the
face) and never wraps a row. Enter opens a profile's
sessions under that profile's box, drawn as on the first page and holding
the gateway record in full (state, pid, how old it is), each platform's error,
each memory target's gauge with its exact entries and characters, and the
sessions by source, a narrow box giving up whole fields rather than cutting
words; the sessions follow in a table box of their own, newest activity
first, under a header row and a rule: title, then, past one divider, model,
input and output tokens, cost, source, last activity and message count,
numbers right-aligned, the highlighted row banded from edge to edge; a narrow
terminal gives up source, then
cost, then tokens before the title runs short (delegated subagent sessions
are counted on the first page, not listed), and Enter again a session's last 40 messages
in a box beneath the session's own (its source, messages, age, model, tokens
and cost), each message's time and role in a column of their own; ← or Esc goes back, q closes it from the
first page, and r reads again at once. It reads again every 5 s by itself, off the screen's own thread.
It counts sessions active in the last 24 hours rather than open ones, because a
messaging gateway leaves every chat it served open, so a Slack bot idle for weeks
would still show dozens. A gateway shows as running only while the process its
record names still runs and is the one that wrote the record (its start time
is compared as Hermes compares it); a platform's state from a gateway that has
since stopped or restarted shows as what was last recorded. Each `state.db` is
opened read-only (and immutable when no connection has it open, so SQLite
creates no file beside it), `config.yaml` and the memory files are read only up
to 1 MiB each (a larger one is reported by size), the OMH store's records are
counted from its directory listing, the only signal it sends is the signal-0
liveness probe, and it calls nothing in Hermes' gateway.

When the OMH TUI cannot start, `omh` says why in one line on stderr and opens
Hermes instead, so you lose the OMH screen, never the session. For a reason
that is the OMH TUI's own — Windows or another terminal without `termios`,
its frontend missing, or a Hermes whose gateway no longer speaks what the TUI
was built for — that is Hermes' own TUI (`hermes --tui`). With `TERM=dumb`,
with `OMH_NO_TUI=1`, or with no Node for Hermes' launcher (Hermes' TUI needs
it too), it is plain `hermes`, which opens what your `display.interface`
chooses. `omh` reopens Hermes' terminal only
on the TUI's own request (exit 75 together with a file `omh` named for that
launch and removes afterwards), so a 75 Hermes returns for a reason of its
own ends the launch like any other exit code. If the gateway stops accepting a method or a key mid-session, the
TUI leaves with the command that reopens the same session in `hermes`; on the
three calls a session does without, reading Hermes' settings (for the busy
mode, which then stays `queue`), reading the command list and the
`/reload-skills` rescan, it says so instead and the session goes on. If
the gateway itself exits mid-session with a failure, the TUI starts it again
the way Hermes' launcher set it up and resumes the same session, saying so
(`The Hermes gateway exited (code 1): starting it again and resuming session
<id> (1 of 3 in 60 s); what you type waits until it is back, and ctrl+c
leaves.`), as Hermes' own
TUI does; each attempt waits up to 15 s for the new gateway, the time Hermes'
own TUI gives one before it reports a slow start (or what
`HERMES_TUI_STARTUP_TIMEOUT_MS` sets, at least 5 s, as there). A question it had asked closes
unanswered, a turn that was running is reported lost and is not sent again,
a steer it had not answered, and what you were typing in an approval's tell
field, come back to the composer at once (never sent), the subagents in the agent view stay there (those still running marked
interrupted, `▪`), and what you queued comes back to the composer as after an interrupt. It
does this at most three times in a minute, and a new gateway that exits
before it resumed the session counts as one of them; after that, or when the
new gateway refuses the resume or does not answer it, it leaves with the command that reopens
the session, `omh --resume <id>` (`hermes --tui` when something other than `omh` opened the TUI),
and Ctrl+C or Ctrl+D while it waits leaves the
same way, the new gateway stopped. A gateway that exits normally, or after you
quit, is not started again. A
turn that brings no event the TUI shows, only types it does not know (Hermes
renamed its turn events), gets one notice pointing at `omh doctor`, which
prints the installed Hermes commit next to the one the TUI was declared
against; a single renamed event among known ones, such as `message.complete`
alone, is not detected, and neither is a renamed `message.*` family that
arrives behind a known event such as `status.update`, `reasoning.available` or
`tool.generating`; either shows as a turn that never finishes.
The gateway, and every tool it runs, inherits the environment `omh`
set for the frontend, `OMH_HOME` included, so `omh --omh-home <dir>` also picks
the store the OMH plugin inside that gateway uses when the profile names none.
The OMH TUI writes no transcript, attachment, secret or Hermes question to
disk, and prompt text in one place only: each line you send from the composer
is appended to Hermes' own input history, `$HERMES_HOME/.hermes_history`, in
the format `hermes --tui` reads and writes, so Up and Ctrl+R reach your earlier
prompts from either terminal. It only appends to that file (creating it mode
0600), reads at most its last 1 MiB, and only when it is a regular file (not a symlink or a FIFO), and never writes an answer to a question
Hermes asked or a masked value there. Everything else it writes
is metadata: the launcher's active-session file, which holds the session id,
what OMH's own HUD reader and model-chain picker write under the OMH home
(the HUD's fan-out cache, and the chains `/omh-model` saves), the skill
names and counts the launch card last drew (`<omh_home>/tui/launch-skills.json`),
and an empty fallback marker at the path `omh` named, which `omh` removes.

The OMH TUI opens with the theme `omh theme use` saved under the OMH home
(see [TUI Themes](#tui-themes)); `/theme <name>` switches the open session only.

A fresh session's launch draws the block logo, the banner's title and a
launch card in one of eight launch looks: `spectrum` (the logo swept through
the tool kind hues, a box per section, the default), `violet` (one box),
`gold` (one box in two columns), `graphite` (grey and white with turquoise
hyphens, a rule above and below), `sakura` (pastel pink, sky blue and cream,
one box), `moonlit` (moonlight yellow and silver over navy, a rule above and
below), `aurora` (emerald and teal into violet, a box per section) or `ember`
(amber through orange to crimson, one box in two columns). The look also
tints the chrome: the composer's rules and the frames drawn like them take
its card-edge colour, and a tool call's rail and the working row's spinner
its label colour (a failed or denied call's rail stays red), as do a sent
prompt's band, the catch rows, the `[⚚ OMH Native]` badge and the working
glow. Body text, the grey details, the reply's rail and the state colours
(running blue, done green, warning amber, failure red) keep the theme's
colours, so a look never changes what a colour says. The card sits under the banner until your first
prompt, then stays in scrollback above it. It names the model and effort,
the new session, the last stored session with its `/resume` id, the first
keys, and the skills Hermes has: OMH's grouped by capability family with
the ulw lanes on a row of their own, and Hermes' own by category. It fills
in as Hermes answers. Hermes names its skills only once it has built the
session's agent, a second or two after the first frame, so until then the
card shows the skills the last launch on the same Hermes home and profile
showed, marked `last-known`, and then replaces them with the session's own; a
first launch, or one on another Hermes home or profile, says `loading…`. The
OMH home keeps one such snapshot, so alternating between Hermes profiles that
share it says `loading…` on each switch. On a
short terminal it drops rows, the last ones
first, never reaching the composer. `/theme` alone opens a picker that
previews each look on the logo, the card and the chrome as you move (arrow keys, `j`/`k`
or a click; once the launch has scrolled away, a compact preview above the
list shows it); Enter keeps the highlighted look, Esc puts the one in use
back, and `/theme <look>` (Tab completes the name) keeps one at once. The look is saved beside the theme, as
`launch` in `<omh_home>/tui/theme.json`; a saved name OMH does not have is
said once and `spectrum` is used. The looks are OMH's own colours: the skin
file Hermes' banner reads is unchanged.
Before its first frame it asks the terminal for its background colour (OSC 11,
in the same wait as the cursor-position query, at most 0.1 s; a terminal that
does not answer can still say light or
dark through `COLORFGBG`: a light background by its colour, a dark one, colour
0 to 6 or 8, as the dark stand-in `/theme dark` uses) and measures the theme
against it: your prompts and the replies are in the terminal's own text colour,
every other colour a word is drawn in reaches 4.5:1 contrast on that background
and every rule or mark 3:1 (on the pager's footer, against its bar: the
theme's own bar colour on a dark background, a light tint of it on a light
one; the info line under the composer and the sticky prompt have no bar),
and
on a light background the diff bands are light tints, their words at 4.5:1 on
each. The menus (the completion menu, the pickers, choice prompts, the agent
list, the delegation view and the bot board) have no band on any background:
the highlighted row is a `❯` and its name bold in the skill hue, at 4.5:1. With no answer and no `COLORFGBG` that names one, the background is
taken as dark, and nothing that would depend on knowing it is painted: your sent prompt gets no band, and a diff band names its own text colour
rather than leave your terminal's on it. `/theme light` and `/theme dark` measure against a
light or a dark background whatever the terminal said, `/theme auto` follows
the terminal again, and each, like `/theme <name>`, redraws the screen in the
new colours.
With `omh --profile <name>` and no `--omh-home`, the OMH home the TUI gets is
the store that profile's config names in
`plugins.entries.omh.settings.omh_home`, when it names one, so it opens with
that profile's theme and its HUD and `/omh-model` read the profile's store.

Bare `hermes` is stock Hermes. OMH writes none of its display keys and
installs nothing into its terminal, so it opens whatever your Hermes config
chooses — the classic REPL unless you set `display.interface` — with no OMH
skin and no HUD. The OMH plugin is still loaded there, so OMH's tools, hooks,
memory and skills work in it; the HUD and `/omh-model` are the OMH TUI's.
An install made before this is migrated by the next `omh setup` or
`omh update`: see [Returning `hermes` to stock Hermes](#returning-hermes-to-stock-hermes).

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

On a machine that never completed `omh setup`, `omh update` bootstraps OMH
instead of skipping it: it installs the plugin bundle (which carries the
Hermes Desktop half), registers and enables OMH in the Hermes config, and
seeds `~/.omh/routing/model-chains.json` — update and setup converge on the same
machine state. One deliberate opt-out is honored: after
`omh uninstall --registration-only` the plugin directory stays in place, so
update never re-registers a machine whose owner removed the registration on
purpose.

`omh update` keeps a Hermes edit, under a narrower rule than `hermes update`
applies to bundled skills. Hermes records every skill edit in its curator ledger
(`<hermes_home>/skills/.curator_ledger.jsonl`), including the ones its
background self-improvement review makes unprompted. `omh update` keeps a
managed skill as it is when the ledger accounts for what is on disk: a changed
`SKILL.md` counts only when the newest ledger write to that file left exactly
its current content, and an unchanged `SKILL.md` counts when a ledger write to
another file of the skill still matches, or a file OMH renders for it that
Hermes removed is still absent. Only the directory OMH renders for the skill
counts: a same-name copy of a managed skill elsewhere in the skills directory
is never kept, carried, or cleared as a Hermes edit, and an edit in a
directory an earlier release rendered the skill into, after a release moved
it, is named in the summary as left behind and is not carried. A kept skill
is carried into the new install (when the install's skill profile includes
it) and named in the summary, and it receives no OMH update until a run with
`--force` clears that directory and renders it again; the summary then says
whether Hermes' ledger still holds a copy of the replaced files, and names any
file it removed that OMH does not render and the ledger holds no copy of.
When a ledger could not be read, those lists count only the ledgers that
could be read: the entry carries `ledger_copy_partial: true`, and one line
after the summary's loss lists names what could not be read. A
change the ledger does not account for, including a hand edit to `SKILL.md`
beside a ledgered change to another file, still stops the update until you
resolve it or pass `--force`. A managed skill whose `SKILL.md` is gone is
rendered again and named in the summary, unless the recorded skill profile
leaves it out; `omh doctor` reports either case under
`missing_managed_skills`, with no `--force` advice. The OMH plugin refuses
Hermes' edits and deletes of managed skills in the first place and points the
model at a separately named skill or the workflow-learning lane instead, and
`omh doctor` reports what the ledger records under OMH-managed skills under
`hermes_skill_edits`.

Each install marks the manifest record of every `SKILL.md` it wrote with the
hash it wrote, and flags the manifest as carrying such marks. Under a flagged
manifest, OMH removes a skill directory (one recorded for a skill the catalog
does not ship, or a top-level directory named for a catalog skill that now
renders in its category directory) only when it rendered that directory, the
`SKILL.md` it rendered there is unchanged, and no Hermes write is recorded
under it; every other file in that directory is removed with it (for a
directory that is also a category, only its own `SKILL.md` and, when it is a
real directory, its `references/` go, and the summary names only what went).
The summary names each directory removed by its path and says what was
checked, and nothing more; the `--json` result lists each one under
`removed_skill_directories` with the rule that removed it. A directory whose
record has no mark is one an install merely found, such as your own skill in a
category directory or a renamed copy beside a managed skill: it is never
removed, with or without `--force`, and is listed under `prune_skipped_skills`
as `not_rendered_by_omh` on every install; the summary names it once, on the
install that first records it. A marked directory whose `SKILL.md` was edited
after OMH wrote it, whose record carries kept Hermes-edit evidence, or under
which Hermes' ledger records any write -- still on disk or not, and whether it
came before or after OMH last rendered there, which OMH cannot tell, since a
removal is final -- is listed as `changed_since_rendered` and left by a plain
install in the skills directory it writes; a staged `omh update` starts its
new generation without that directory, as it does without any other local
change that is not a kept Hermes edit, and the directory stays in the previous
generation. `--force` removes it, except under `OMH_SECURITY=strict`, where
`--force` overrides no local change, and lists it under `force_pruned_skills`,
with the files Hermes' ledger still holds a copy of and the files that are
gone for good; when a ledger could not be read, that entry carries
`ledger_copy_partial: true` and the summary says the lists count only what
could be read, naming what could not. A Hermes curator ledger that exists but
cannot be read (for example a permission error, or bytes that are not UTF-8),
that holds a line naming a path in the skills directory that is not a ledger
row, or whose last line has no line end (an append may be in progress), may
record such a write, and so may a bot profile's ledger when
`<hermes_home>/profiles` cannot be listed or an entry in it cannot be read. So
a marked directory with nothing else against it is listed as
`ledger_unreadable` and left in place, with what could not be read and its
error named in the summary (and under `unreadable_ledgers` in the `--json`
result, each ledger once: more than one torn line is named by a count and the
first line number, a single one by its line number); a ledger that does not
exist records nothing. `--force` removes it on the same terms, and names what
could not be read instead of what the ledger holds. A manifest
written before marks existed is handled once more by the earlier rule, which
does not know what OMH rendered or look for Hermes writes: an unchanged record
at the top level or in a category directory, inside the skills directory, is
removed, including a directory of your own there, and `--force` also removes a
changed one. The summary names each directory that install removed by its
path and says that OMH cannot tell whether it rendered it, and the manifest
that install writes carries marks from then on.
Under either rule a directory is never removed when it resolves outside the
skills directory, when it is a category directory or holds other skills, or
when it is, under another spelling, a directory OMH renders a skill into (a
render directory renamed to another letter case on a case-insensitive
filesystem). An edit reported as left behind is likewise never removed while
the catalog ships its skill, with or without `--force`: it stays until you
delete its directory yourself, which the summary says each time it names it.

Plugin reinstalls protect local additions as well as edits to managed files.
If `$HERMES_HOME/plugins/omh/` contains entries absent from its installed OMH
manifest, `omh setup` refuses replacement and names those entries. `omh update`
leaves that plugin tree unchanged and prints a warning while continuing its
other updates. Dry runs apply the same protection without writing plugin files.
Move additions outside the plugin directory before retrying, or use
`omh setup --force` / `omh update --force` only if you intend to discard local
changes and additions inside that directory. Unchanged files listed in an older
manifest can still be refreshed or removed when the current bundle retires them.
Recognizable Python bytecode caches for managed sources do not block refresh.
A cache written by omh's own Python qualifies only as a bounded, complete
timestamp or hash `.pyc` with a valid code-object payload (the cache is parsed,
never executed); oversized, truncated, non-code, or trailing-data payloads
remain protected as additions. Hermes imports the plugin with its own Python,
which may be another version, so a cache under another version's tag qualifies
by its well-formed header alone; a foreign header under omh's own tag does not. The staged
replacement checks the renamed original again before installing; late additions
or managed edits that diverge from the incoming bundle cause a refusal and
restoration of the original directory.
If a plugin tree appears after an initially empty path was inspected, setup
restores it instead of treating it as the original tree, even with `--force`.
A tree that becomes Hermes-managed during staging is likewise never replaced
by OMH, including forced refreshes.

Replacement uses an invocation-owned private transaction directory alongside
the plugin. Existing `.omh.previous` and `.omh.installing` siblings, including
symlinks, are never cleared, even with `--force`. If replacement fails, OMH tries
to restore the original tree; if rollback also fails, the error names the
retained backup for manual recovery. Inspect any old recovery directories before
removing them yourself. Hermes-managed plugin installs remain Hermes-owned:
`--force` does not override that boundary; use `hermes plugins update omh`.

The installed bundle carries a Hermes Desktop half at
`plugins/omh/desktop/plugin.js` and a HUD backend route at
`/api/plugins/omh/hud`. `omh doctor` reports `plugin_desktop_half` for whether
the bundle carries its files, and `plugin_enabled` for local Hermes config;
neither check proves Desktop copied, enabled or mounted the half. Rescan in
Desktop (Capabilities -> Plugins -> Rescan, or restart the app), inspect the
Plugins page, and verify the pane/backend in that runtime before reporting
it ready. The pane is intended to show the plan checklist, agent rows and active
fanout DAG. `omh uninstall --registration-only` does not disable the plugin or
change `plugins.enabled`. Desktop mounting must be observed separately.

An explicit `--source` or `--from-skills-dir` remains a workflow-content-only
operation, and `--dry-run` never changes the command package. A source checkout
or other unmanaged Python environment is not rewritten implicitly; the result
reports the supported installer command instead.

On installer-managed installs (the curl and PowerShell paths), the update is
staged rather than applied in place. OMH builds the new command environment and
its workflow pack off to the side, smoke-tests them, and only then swaps them in
with a single pointer move. This keeps the command and workflow pack paired;
it does not make shared plugin/config refreshes atomic. If the new version fails
its post-activation check, OMH attempts to restore the previous pointer and
re-enters that version to restore shared resources. A failed restoring reentry
leaves recovery required, even when the pointer is already back. To select a
retained known-good generation deliberately, run:

```sh
omh update --recover-known-good
```

See [Staged installer updates and recovery](#staged-installer-updates-and-recovery)
for what is on disk and what the JSON payload reports.

### Verify or troubleshoot the installation

Run doctor separately after setup:

```sh
omh doctor
```

Doctor has two independent privacy controls, which also work with `--json`:

- `--no-personal-files` does not open or read the bodies of `SOUL.md`,
  `memories/MEMORY.md`, or `memories/USER.md`. The
  `soul_missing_or_starter` and `hermes_memory_staleness` advisories remain in
  the report as `skipped`, with a reason saying they were not run; they are not
  passing or failed observations. Other checks and advisories are unchanged,
  and Hermes `config.yaml` reads still happen.
- `--no-state-write` does not create or update `runtime/state.json` and skips
  the `.doctor-write-test` writes for `runtime_artifacts` and `workflow_state`.
  Those checks report `write access not probed` and use a non-writing
  permission check instead of claiming observed writability. JSON output has
  an empty `state_log` and a `privacy_controls` marker; human output says state
  write is disabled. This control removes doctor's state and probe writes
  under the OMH home, including on check or advisory error paths. It does not
  make every subcheck write-free: the separate Hermes loader-registration
  smoke can still copy the plugin into a temporary directory when a Hermes
  install is found, so this flag is not a promise of no writes anywhere.

For managed plugin upgrades, a local file whose bytes are identical to the
incoming bundle does not block a non-forced `omh setup` or `omh update`, even
when its hash differs from the older installed manifest. The normal install
rewrites the manifest. A locally divergent file still requires `--force`, and
the staging revalidation applies the same distinction.

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

### What the Hermes interpreter must be able to import

`omh setup` copies the plugin bundle to `$HERMES_HOME/plugins/omh`, and
installing `omh` from Hermes' plugin catalog places the same bundle there.
Hermes loads it with **its own** interpreter. Every documented install —
Homebrew, bun, npm, the universal installer, `uv tool install`,
`pip install --user` — puts the `omh` **package** in OMH's environment, not
Hermes'. On most machines the Hermes interpreter therefore cannot import `omh`
at all.

That is a supported state, not a broken one. Hermes still registers every tool
and hook of the plugin. Every module of the bundle imports without the package:
the imports that need it are guarded, and the features it carries report their
own absence instead of failing. These features live in the package rather than
the bundle, so absence turns them off:

| Feature | Behavior when Hermes cannot import `omh` |
| --- | --- |
| Agent board (`omh_agent_board`) | Answers `unavailable` with reason `omh_agent_board_core_unavailable`, and leaves native `kanban_*` calls alone. See [Agent board and native Kanban coordination](AGENT-BOARD.md). |
| Native Loop (`omh_loop`) | Answers `service_unavailable` with a `package_backend` block whose `status` is `absent`, and reads or writes no Loop state. The `omh loop` CLI reaches the same Loop store when it is given that profile's OMH home: `omh --omh-home <that home> loop status`. |
| Connector decision gate (`omh_decision_gate`) | A payload of the required shape answers `unavailable` with reason `package_backend_absent` and the same `package_backend` block, and records no gate answer. See [Decision-gate connectors](DECISION-GATE-CONNECTORS.md). |
| Team gate (`omh_team`) | Answers `refused` with reason `omh_team_core_unavailable`. |
| Source-trust ceiling (`omh_source_trust`) | Answers with `ceiling_applied: false` and no summary, so an unenforced answer cannot read as an enforced one. |
| Local activity observer engine | `register` reports `observer_setup_failed`; the rest of the plugin still loads. See [Session activity receipts](SESSION-ACTIVITY-RECEIPTS.md). |
| Route hint for your own trigger packs | A phrase that only a pack under `<omh-home>/routing/trigger-packs/` recognises gets no route hint in chat; `omh chat route-hint` still hints it. |
| Coding owner on coding-delivery route hints | The hint asks the user to choose the executor instead of carrying the router's coding-owner decision. |

The route hint itself still works without the package. It uses the bundle's own
copies of the router's cue tables, guards and classifiers, so for some messages
it disagrees with `omh chat route-hint`: it hints a different workflow, hints
none where `omh chat route-hint` hints one, or hints one where it hints none.

`omh_probe` reports which state a host is in, apart from registration: its
`package_backend` row reads `available`; `absent` (the interpreter has no
`omh` package, the state above); `incompatible` (an `omh` that does not provide
what this bundle imports: an oh-my-hermes of another version, or an `omh`
module that is not an installed oh-my-hermes package at all); or `broken`
(any other failure while importing it, including one that is not an
`ImportError`). When the package's own probe cannot be imported, `omh_probe`
answers from the bundle and adds a `package_probe` row whose `absent`,
`incompatible` or `broken` says why that import failed; the `package_backend`
row still reports the Loop backend, which can import while the probe does not. `omh_loop` and
`omh_decision_gate` carry the same block, with the plugin's own version beside
the package's, whenever they refuse for one of these; the other tools in the
table above keep their own refusals.

To turn these features on, the interpreter Hermes runs must be able to import
`omh`. Whether there is a supported way to arrange that depends on who owns
that environment:

- **An environment you manage yourself**, one Hermes' package manager does not
  prepare: install `oh-my-hermes` there as well, at the version of the plugin
  bundle, so `omh` is importable from both. Nothing else changes: the bundle,
  the configuration, and every doctor check stay the same.
- **An environment Hermes' package manager prepares** (`hermes pm`, which
  admits a plugin's Python dependencies when the plugin is installed or
  enabled): there is no supported way yet. Hermes admits only the
  dependencies a plugin declares and does not manage direct-URL requirements,
  and `oh-my-hermes` is not published to a package index, so the bundle
  declares none. Do not add the package to that environment with `pip` or
  `uv` by hand: Hermes' rules forbid it, and its developer guide says
  "Dependencies installed manually with pip are not durable PM declarations".
  Until then, the `omh loop` CLI is the way to drive a Loop from that host.

What is **not** supported is a bundle module that imports `omh.*` at module
level without a guard. Hermes' memory-provider lane execs every top-level file
of the bundle and keeps the module in `sys.modules` when one raises, so the
next import of that module fails on the name, its feature is silently dead, and
every tool call that reaches it logs a hook warning (#1623). `omh doctor` reads
the installed bundle and reports this as `plugin_bundle_standalone_imports`,
naming the module and the import:

```text
plugin_bundle_standalone_imports: 1 module-level import(s) in
/Users/you/.hermes/plugins/omh cannot resolve on a host without the `omh`
package: agent_board_bridge.py:36 `from omh.workflows.agent_board import
AgentBoard`. ...
```

A machine reaches that state when the installed copy is stale, hand-copied, or
locally edited rather than written by OMH. Run `omh update` to reinstall the
managed bundle from the current OMH package (`omh setup --force` if this copy
carries local edits you are willing to replace), then restart Hermes Agent and
run `omh doctor` again.

Hermes 0.21.5 and later (and canary builds from 2026-09-25) also put a
deadline on that load: a plugin's import plus `register()` must finish within
`plugins.load_timeout_seconds` (10 seconds unless the Hermes config sets it;
`0` turns the deadline off), or Hermes skips the plugin for that load and its
plugin loader registers no OMH tool or hook. The bundle loads cold in
0.4-0.8 s on a contended 14-core Mac (2026-10-13), and
`tests/test_plugin_load_deadline.py` holds it under half the default; on
Windows the only measurement is the timing that test prints in CI.
`omh doctor` reports the `plugin_load_deadline` row: the value it read from
the Hermes config, and whether `<hermes-home>/logs/errors.log` or its two
rotated backups hold a line Hermes writes when the deadline costs `omh` its
load. A record there is a past load, so check `/plugins` in a running session
for the current state; files with no record are named for what was read of
them (at most the last 4 MiB of each) and are not proof the plugin loaded;
and a missing log reads `not_observed`.

## Guided Model Setup

Normal users can ask Hermes **set up my models**. The CLI in this section is an
**agent/maintainer** configuration and diagnosis surface, not a prerequisite for
installing or using OMH.

The guided flow is deliberately staged:

1. **Inspect.** `omh setup --model-setup` scans bounded, allowlisted metadata
   roots for Codex, Claude Code, Hermes, OpenCode, and the pi-family runtime
   with its host CLIs. Discovery does not
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
  --confirm-model openai-codex/gpt-6.1-sol \
  --confirm-model google/gemini-4-argon \
  --model-alias main=openai-codex/gpt-6.1-sol \
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
compatible alternative, so a model that heads no chain stays a valid
user-selected alternative. If no candidate is
confirmed for the selected category, role-slot, and domain chains, the resolver
consults one shared final order: Claude Opus 5.5, then GPT-6.1 Sol. These names
remain editorial candidates filtered through caller-confirmed metadata; they
do not prove subscription, entitlement, authentication, or runtime readiness.
If no candidate is confirmed anywhere, the resolver records `owner_default`;
Hermes or the selected external owner keeps its native default model, setup
completes with `status: defaulted`, and no model-config write is prepared or
applied.

### Editable recommendation categories

The shipped catalog is editorial policy, not benchmark output:

<!-- omh:model-chain-table:begin (generated: uv run python -m omh.cli docs chain-table; source: src/coding/model_recommendations.py) -->
| Surface | What it is for | Shipped editable order |
| --- | --- | --- |
| Hermes `main` suggestion | The session's own model | GPT-6.1 Sol (`high`), Claude Opus 5.5, Claude Fable 5.1, GPT-6 Astra (`xhigh`), Kimi K3.1 Pro |
| `ultrabrain` | Deepest reasoning | GPT-6 Astra (`xhigh`) |
| `deep` | Strong default tier | Claude Opus 5.5 (`high`), GPT-6.1 Sol (`high`), Kimi K3.1 Pro (`high`) |
| `architect` | Architecture and system design | Claude Opus 5.5 (`xhigh`), GPT-6 Astra (`xhigh`), Claude Fable 5.1 (`xhigh`), Kimi K3.1 Pro (`xhigh`) |
| `unspecified-high` | Default working model | GPT-6.1 Sol (`medium`), Claude Opus 5.5 (`medium`), Kimi K3.1 Pro (`medium`) |
| `unspecified-low` | Cheaper fallback | GLM 5.3 (`low`), DeepSeek V4.1 Flash (`low`), GPT-6.1 Sol (`low`), Claude Sonnet 5.5 (`low`) |
| `quick` | Short tasks | GLM 5.3 Flash (`low`), GPT-6 Luna (`low`), Claude Haiku 5.5 (`low`), Kimi K3.1 Pro (`low`) |
| `writing` | Prose and docs | Claude Opus 5.5 (`medium`), Claude Sonnet 5.5 (`medium`), Kimi K3.1 Pro (`medium`), Gemini 4 Argon (`medium`) |
| `visual-engineering` | Frontend and visual | Claude Opus 5.5 (`high`), Claude Fable 5.1 (`high`), Gemini 4 Argon (`high`), Kimi K3.1 Pro (`high`) |
| `artistry` | Unconventional work | Gemini 4 Argon (`high`), Claude Opus 5.5 (`high`), Claude Fable 5.1 (`high`), Kimi K3.1 Pro (`high`) |
| `capable` | Strong general work | Claude Opus 5.5 (`medium`), GPT-6.1 Sol (`medium`), Claude Fable 5.1 (`medium`), Kimi K3.1 Pro (`medium`) |
| `simple-work` | Small everyday tasks | GPT-6 Luna (`low`), Claude Haiku 5.5 (`low`), DeepSeek V4.1 Flash (`low`) |
| `deep-work` | Long tasks at frontier depth | Claude Opus 5.5 (`max`), GPT-6.1 Sol (`max`) |
| `google-search` | Research grounded in Google Search | Gemini 4 Argon (`medium`), GPT-6.1 Sol (`medium`), Claude Opus 5.5 (`medium`) |
| `x-search` | Live search on X | Grok 4.7 (`high`), Kimi K3.1 Pro (`high`), Gemini 4 Argon (`high`) |
| `review` | A different model tries to break the diff | GPT-6.1 Sol (`xhigh`), Claude Opus 5.5 (`xhigh`), Kimi K3.1 Pro (`xhigh`) |
| `swarm` | Many parallel workers on separate slices | DeepSeek V4.1 Flash (`low`), GLM 5.3 Flash (`low`), GPT-6 Luna (`low`) |
| `forensics` | Root-causing a live symptom or a captured trace | GPT-6 Astra (`xhigh`), Claude Opus 5.5 (`xhigh`), Kimi K3.1 Pro (`xhigh`) |
| `synthesize` | Merging many results into one answer | Claude Opus 5.5 (`xhigh`), GPT-6.1 Sol (`xhigh`), Gemini 4 Argon (`high`) |
| `x_platform_data` affinity | X-platform data affinity | Grok Build 0.1, Kimi K3.1 Pro, Gemini 4 Argon |
| Shared final order (`last_resort.any`) | Last resort when a chain is exhausted | Claude Opus 5.5 (`medium`), GPT-6.1 Sol (`medium`) |
<!-- omh:model-chain-table:end -->

Chain customization is a config edit, not a source edit — bare
`omh model-chains` (or `omh model`) opens an arrow-key picker on a terminal:
one row per category, up/down to move (stopping at the first and the last
row), left/right to step the head model through the aliases chains name
today, `-`/`+` to step its effort, `d` to restore the shipped default, Enter
to save and Esc (or `q`) to leave the file alone;
inside the OMH TUI, `/omh-model` opens the same picker over the
transcript (Hermes' own `/model` picks the session model and keeps its name;
the two edit different things); `omh model-chains show` prints the current
per-category state, `omh model-chains interview` walks every category with
numbered choices — the
interactive `omh setup` offers that walk right after its provider question,
default No, and a "no" leaves the seeded defaults in effect — and
`omh model-chains set <category> "model[:effort], ..."` is the scriptable
write (agents included).

![Bare omh model-chains on a fresh OMH home: one row per category with its shipped head model, effort bar and state; the cursor row shows the left/right and -/+ handles, and the key row ends with esc cancel](../assets/model-chain-picker-cli.png)

All of them edit the same document: `omh setup` seeds
`~/.omh/routing/model-chains.json` (`mixture_chain_overrides/v1`) with an
empty `categories` object, meaning the shipped defaults above stay live and
keep updating with `omh update`. A category written into that file replaces
its whole chain — for delegation routing, `omh_delegate_route` fallback
walks, and HUD category labels alike — until the user removes it. An invalid
document is ignored whole (defaults apply) and reported by
`omh_delegate_route` `action=status` as `chain_overrides: invalid: ...`.

A fresh seed, and an edit that replaces two chains:

```sh
$ cat ~/.omh/routing/model-chains.json
{
  "categories": {},
  "schema_version": "mixture_chain_overrides/v1"
}
```

```json
{
  "schema_version": "mixture_chain_overrides/v1",
  "categories": {
    "architect": [
      {"model": "claude-fable-5-1", "reasoning_effort": "xhigh"},
      {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"}
    ],
    "quick": [
      {"model": "deepseek-v4.1-flash-ultrafast", "reasoning_effort": "low"},
      {"model": "glm-5.3-ultrafast", "reasoning_effort": "low"}
    ]
  }
}
```

The Ultrafast models in that example, DeepSeek V4.1 Flash Ultrafast and GLM
5.3 Ultrafast, are served on [OpenGateway](https://opengateway.ai/). The
interview's Ultrafast option swaps a chain member for its `-ultrafast` id only
when OMH knows that id. Among the shipped chains it appears only for
`unspecified-low`, whose GLM 5.3 entry has one. GLM 5.3 Flash has no
Ultrafast id, and the chains name DeepSeek's `deepseek-flash` pointer, which
has none of its own either.

Next to those two documents, `omh_delegate_route` maintains
`~/.omh/routing/route-provenance.json` (`delegation_route_provenance/v1`): a
capped history of the routes it prepared (head, explicit, fallback, chain
exhaustion, clear) that the HUD uses to label a fallback lane as a fallback,
an exhausted chain as `category(model inherit)`, and a lane routed to the
model the parent session itself runs as that lane's own category — one
`category(model tag)` shape for every lane, where the category names the
lane and only the parenthesized model and state token move. The state token
names an event in the route (`fallback`, `inherit`) and nothing else; a lane
that landed on the parent's own model carries none, because the row already
names the model that ran. The `read_omh_hud` payload still reports it as
`same_as_parent` for a caller that holds both models. A child on the
parent's model with no route record at all is the plain `inherit(model)`:
inherit is not a category. Each record also names the Hermes session that
prepared the route, so a HUD reading one conversation labels the lanes that
conversation routed and leaves another conversation's alone; a record
written before that field existed names no session, and a session-scoped
HUD leaves those unclaimed rather than guessing. It is written
automatically, carries its own `claim_boundary` (prepared routes only,
never dispatch evidence), and is safe to delete — an absent or invalid file
only means HUD rows fall back to plain category projection.

Beside it, `~/.omh/routing/route-restore.json`
(`delegation_route_restore/v2`) holds the way back out of a route. The first
time OMH writes `delegation.*` over values it did not write, it records what
those three keys held — a key the file did not carry is recorded by being
absent, so putting the baseline back removes the key rather than writing an
empty string — together with what OMH wrote and which session wrote it. The
baseline is captured once and survives later routes. A candidate baseline
that exactly matches the newest route in `route-provenance.json` is OMH's
own leftover rather than a value the person set, and is recorded as "keys
absent" with `baseline_origin: omh_leftover`. Two things follow that are
worth knowing before pinning a model by hand. Pinning exactly the model,
provider and effort OMH last wrote is indistinguishable on disk from OMH's
own leftover, and such a pin will not be restored. And if
`route-provenance.json` is missing or unreadable the check cannot run, which
is reported as `baseline_captured_provenance_unavailable` rather than
assumed either way. The record also names the `config.yaml` it describes,
since two profiles may share one OMH home.

A route is scoped to the task that wrote it. `action=clear`, the end of that
task, and the start of a later session when the writing session is gone all
put the previous values back; chain exhaustion puts them back instead of
clearing, and will not remove a value OMH cannot prove it wrote. In the TUI
and the CLI a task is one turn, so a route lasts one turn. On a gateway
platform (Slack, Discord, Telegram, Feishu, the API server) the task id is
the session id, so a route lasts the session.

A route is also the route of the conversation that set it. The three keys
are shared by every session on the profile, so `~/.omh/routing/conversation-routes.json`
(`delegation_conversation_routes/v1`) records which conversation asked for
which route, and just before Hermes reads the keys for a `delegate_task`,
OMH's `pre_tool_call` puts that conversation's own route back if another
session replaced it. A delegate child that dispatches its own workers (with
`delegation.max_spawn_depth` above 1) gets the route of the conversation it
was delegated from, found through the `_delegate_from` marker Hermes writes
on the child's `state.db` row. A conversation that set no route in this task
gets the profile's default instead of another session's live route. Another
session's `set`, `clear`, `fallback` or turn-end restore therefore changes
which route the keys hold between dispatches, but not which route a dispatch
runs on. A recorded route ends with its task, at the turn end or at the
session-start restore that takes it back, and one older than six hours is
ignored. When OMH cannot put the right route in place (another writer holds
the lock for two seconds, or the write is refused), the `delegate_task` call
is refused with `route_overwritten_by_other_session`, `route_not_applied` or
`other_session_route_live`, naming both sessions, and no child starts. A
dispatch whose unlocked read found nothing to change goes ahead when the lock
is busy. A `clear` or an exhausted chain whose release of the conversation's
entry fails does not bring the route back: before the release it records the
entries it takes out in `~/.omh/routing/conversation-take-outs.json`
(`delegation_conversation_take_outs/v1`), whatever the restore found, keyed
like the entries (the session, or `task:<id>` for a host that names no
session), and a dispatch ignores an entry recorded there. A `set` that wrote
its route but not its conversation entry does not get the conversation's older
route put back over it either, even after another session's `set`: before the
entry, each `set` records the route it wrote in
`~/.omh/routing/conversation-writes.json`
(`delegation_conversation_writes/v1`), one stamp per writer keyed like the
entries. An entry older than its own stamp is replaced by that stamp, so the
conversation's dispatch, and a delegate child inheriting from it, runs on the
route it set last. Any other older entry of the same writer (the same task,
or the same session when neither names a task) that names another route is
ignored. A stamp never brings back a route a `clear`, a chain exhaustion or a
turn end took out: it stands in only for an entry still recorded, and each of
those marks the conversation's stamps released before it removes the entries,
so a removal that fails does not let the stamp stand in either. A delegate
child inherits the newest route the conversations it descends from wrote,
including across a compaction, and never one older than the same
conversation's newest stamp or take-out; a later write by a grandparent's
conversation does not hide the parent's route. Stamps are kept for six hours, at most 64 of them,
and a missing or unreadable file reads as "no newer write". Two
cases are left in place as before: a route whose writer recorded no
conversation entry, such as one written by an older OMH that is still
running, and any route when the dispatching session's own `state.db` row
cannot be read, since that session might be the route's child. That second
case is not silent: the call still goes ahead, and the hook result carries
`omh_route_fallback` (`lineage_unresolved`, naming both sessions) and Hermes'
log gets a warning from `omh.delegation_route`. `action=status` reports the
calling conversation's own route as `conversation_route`, beside the
profile-wide keys in `route`, with `in_keys` saying whether the keys hold it
now.

One window remains: Hermes reads the keys after the hook returns, so a write
by another session in that interval still wins. When another check asks a
person to approve the `delegate_task` first, the route is written before
they answer, so the wait for the answer is part of that interval. A released
Hermes offers no per-call route that would close it. With
`HERMES_IGNORE_USER_CONFIG=1`, Hermes ignores the `config.yaml` OMH writes,
so no route applies at all.

Every one of those is gated on the same recorded value: if the keys no
longer hold what OMH wrote, someone else set them, and OMH reports that and
changes nothing. The session-start path additionally asks the writer's own
`state.db` row whether it is still running. Only a row the host closed
answers that it is not; a row the host never closed, which is what a killed
TUI and most gateway sessions leave behind, falls back to a six-hour bound
on the route's own age. Such a route can outlive its session by that long
rather than risk being taken back while the writer is still dispatching.
A row Hermes closed to compact the conversation (`end_reason` `compression`,
which its rotating compaction writes when `compression.in_place` is `false`)
does not answer either: the conversation goes on in a new row, so the
question goes to the rows Hermes continued it in, following only the
continuation links Hermes itself writes. If those rows cannot be read or do
not match how Hermes records a compaction, the route stays and the restore
reports `continuation_unverified`, but only until the route is six hours old,
the bound a writer row that cannot be found gets; after that it is put back
and reported as `continuation_unverified_expired`.

What returns is the previous values, not the previous bytes: the writer
normalises quoting, emits the three keys in a fixed order, and drops an
inline comment on one of those lines, leaving every other byte untouched.

If the record itself fails to write after a route has landed, the route is
reported as unrecorded and whatever the keys held before it is gone with the
record, so a model pinned by hand will not come back. Deleting the file by
hand is safe and means only that OMH stops claiming it knows what the keys
held before it.

A fourth sibling, `~/.omh/routing/dispatch-models.json`
(`omh_dispatch_model_preferences/v1`), applies to a different surface:
`omh coding fanout dispatch`'s `--model` fallback for a spawned agent CLI,
used only when a unit's prepared handoff routed no model at all. It is
operator-edited (the interactive `omh setup` maestro question seeds it empty
on an explicit "yes"; nothing else writes it). See `docs/FANOUT.md`
(Dispatch-model preference) for the schema and the `claude-code`/`codex`
behavior it fills the gap for; on `omh coding run` it sits below that
command's own `--model` flag and any routed handoff model, above only the
executor CLI's own default.

A fifth sibling, `~/.omh/routing/category-maestro.json`
(`omh_category_maestro/v1`), is the Maestro lane's own category dial — the
same category vocabulary as the mixture above, applied to the dispatched
`codex`/`claude-code` CLIs. `omh coding category-maestro show` prints the
effective category → model table (operator overrides marked, invalid pieces
named), `omh coding category-maestro set <profile> <category>
<model[:effort]>...` is the scriptable write,
`omh coding category-maestro clear` restores a built-in chain, and
`omh coding category-maestro interview` walks it guided — the interactive
`omh setup` offers that walk right after the maestro question. The file's
presence is the opt-in: machines without it keep byte-identical routes, and
routes resolved against it record `catalog_kind: "operator_category_config"`
plus the config fingerprint in the frozen contract. Catalogless profiles
(for example the `pi-family-runtime` profile and its host CLIs) are
deliberately not configured here — their categories resolve from the
locally-derived model catalog (that runtime's own config). See
`docs/FANOUT.md` (Category-maestro) for the full
rules.

### Reaching models through a provider

Chains name models the way a person says them (`glm-5.3`, `kimi-k3.1-pro`). A host
that reaches models through a provider usually needs two different values
instead: a provider id, and that provider's own model string, which is often
namespaced like `vendor/model-name`. Which provider serves which model, and
under what name, belongs to one account — so OMH ships no routes and hardcodes
no provider.

Which providers and subscriptions a machine holds is a third, separate
question. The interactive `omh setup` asks it as one ticked list of the
services you have an account, key, or login for: every provider family, plus
each provider id in Hermes' config (`providers.<id>` and `model.provider`,
except `auto`) and each builtin provider whose key NAME appears in
`$HERMES_HOME/.env` or the environment (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, ...; values are never read), plus OpenGateway — OMH's own
gateway, offered whether or not `OPENGATEWAY_API_KEY` is set yet, because a
row that appears only once the key exists is a row nobody discovers. Rows
found on the machine arrive ticked, because a found config key or variable
name is a sensible default — it is not proof of a working account, so every
ticked row can be cleared and only what you leave ticked is recorded.

The list's last row is **Skip — leave everything as it is**. Choosing it
writes nothing at all: no entitlement document, no dispatch-model seed. An
earlier record stays as it is, and the providers Hermes is linked to keep
counting on their own (see below), so the machine behaves exactly as it does
for someone who never answered — which is not the built-in chain order
unless nothing is linked. It is exclusive — ticked beside a provider the
prompt asks again rather than guessing which half you meant — and it is
never pre-ticked.

The row just above it is **Other provider — type its name**. Tick it to add a
provider id the list does not show: after Enter you type each id (each is
asked for its kind, since OMH knows nothing about it) and an empty line ends
the list. Left unticked, Enter on the list ends the step without that
prompt. Like skip it is never pre-ticked, and ticked beside skip the prompt
asks again. Picking it never unticks another row. In the typed menu, where a
typed answer otherwise replaces the ticked rows, an answer naming only this
row is added to them. In the arrow-key menus, including the kind menu that
follows a typed name, a two-digit row number is typed as its two digits. A
note under the menu shows a first digit that is still waiting, and Space or
Enter picks that row instead. Then, when the Claude Code CLI is
on PATH, you are asked whether you have a Claude Code subscription. The
answers are recorded in `~/.omh/routing/providers.json`
(`provider_entitlements/v1`):

```json
{
  "schema_version": "provider_entitlements/v1",
  "providers": {"og": "gateway", "zai": "zai"},
  "subscription_clis": ["claude-code"]
}
```

You do not have to answer for the common case. OMH reads the providers
Hermes is already linked to and counts them on its own, the moment they are
linked: the ids under `providers` in `auth.json` and the `credential_pool`
entries Hermes itself counts (a `hermes auth` device-code or PKCE login, a
manual add, an `env:`-seeded row whose variable is still in `.env` — never a
credential borrowed from another CLI), every `providers.<id>` key and
`model.provider` in `config.yaml`, and the API-key variable NAMES Hermes'
registry lists, read from `$HERMES_HOME/.env`. A key exported only in a
shell is not counted (Hermes did not record it; the interview below still
offers it). Only ids, names, and a pool row's `source` label are read —
never a token or a key — and nothing is invoked. A registry id carries its
vendor family (`openai-codex`, `zai`, `kimi-coding`); an id OMH cannot place
is your own endpoint, and the block says where it points — a `base_url`
naming a vendor's documented API host (`openrouter.ai`, `api.deepseek.com`,
`api.z.ai`, …) carries that vendor's family, exact hosts only, so a private
relay of your own is never renamed after a vendor whose name happens to
appear in its URL — and anything else counts as a `gateway` unless the
`base_url` is a loopback address (LM Studio, a local Ollama), which is left
out entirely; a Hermes
provider whose models the catalog never describes (MiniMax, StepFun) is
ignored rather than guessed, and so is `CLAUDE_CODE_OAUTH_TOKEN`, which
Hermes' registry marks implicit. The recorded document sits on top: its kind
wins for an id both name, it is the only source of `subscription_clis`, and
a linked row you untick in the interview is written as `excluded_providers`
and stops counting — the one way short of unlinking it from Hermes. Beyond
that neither side removes the other's providers. `omh model-chains show`,
the CLI picker, and `/omh-model` list the providers counted, each with where
it was found (`login`, `config`, `env`, or `recorded`).

A private gateway is the case no host can answer, and the interview does not
answer it either: a detected `providers.<id>` row arrives ticked at the kind
detection gave it, and re-entering the same id after the list is refused as
already recorded — while a `--yes`, `--json`, or non-TTY `omh setup` asks no
provider question at all. So recording what such a provider serves is a
command, for people and install scripts alike:

```sh
omh model-chains provider set work-gateway openrouter   # record what it serves
omh model-chains provider clear work-gateway            # go back to detection
```

It writes the same `providers.json` through the same validation the
interview uses, refuses a kind outside the vocabulary by naming the accepted
values, refuses to overwrite a record it cannot read, and is idempotent — so
an install script can run it on every run. `omh model-chains show` says when
a machine's providers all resolve to nothing, and names this command as the
way out.

With linked providers found or that document present, every chain is
reordered so the entries such a provider can serve lead and the rest follow;
nothing is removed, so a wrong answer costs one rejected fall-through, never
a missing model. A gateway, `openrouter`, `opencode`, or `unknown` kind
serves every family; any other vendor kind serves only the models whose
editorial candidates name it; an explicit route in `model-providers.json`
decides before either. The same reordered chains feed `omh_delegate_route`,
the HUD labels, and `omh model-chains show`, which marks a reordered chain.
A confirmed Claude Code subscription is a Maestro-lane entitlement: Hermes
cannot spend it, so its only effect is seeding the Claude Code `--model`
preference in `dispatch-models.json` when none is set (a Codex login is
spent by Hermes' own `openai-codex` provider and is counted under providers
the moment `hermes auth` records it). `--yes`, `--json`, and runs without
`--interactive` on a non-TTY ask nothing and write nothing; rerun `omh setup`
interactively to answer again (existing answers arrive pre-ticked) or edit
the file.

Supply wire-id routes in `~/.omh/routing/model-providers.json`
(`model_provider_routes/v1`), a sibling of the chain document:

```json
{
  "schema_version": "model_provider_routes/v1",
  "models": {
    "glm-5.3": {"provider": "my-gateway", "model": "z-ai/glm-5.3"},
    "kimi-k3.1-pro": {"provider": "my-gateway", "model": "moonshotai/kimi-k3.1-pro"}
  }
}
```

### Token prices

The cost figures OMH shows when a host records none are ballparks from a
shipped table, and what you actually pay is not: a gateway applies its own
markup, an enterprise contract is not the list price, a free tier bills
nothing, and vendors reprice. Put your own rates in
`~/.omh/routing/model-prices.json` (`model_price_overrides/v1`):

```json
{
  "schema_version": "model_price_overrides/v1",
  "models": {
    "claude-fable-5-1": {"input_per_mtok": 8.0, "output_per_mtok": 40.0},
    "grok-build-0.1": {"input_per_mtok": 1.0, "output_per_mtok": 2.0},
    "my-free-tier-model": {"input_per_mtok": 0, "output_per_mtok": 0}
  }
}
```

A model listed here uses your rate; a model not listed falls back to the
shipped ballpark, and a model neither prices reports no cost at all rather
than claiming it was free. `cache_read_ratio` is optional and defaults to the
shipped ratio for that model. Zero is a real rate, not an absent one, so a
free tier can say so. Validation is strict and atomic, like its siblings: an
invalid document is ignored whole rather than half-applied.

A recorded cost from the host is never replaced by any of this — overrides
only reach the approximation that fires when nothing was recorded, and an
approximated figure still renders with its `~` marker. A row whose figure
came from your own rate is marked `cost_override` beside `cost_approximate`,
so a number you chose can be told apart from our shipped ballpark.

"Nothing was recorded" covers two shapes, both of them the host declining to
state a cost: no cost provenance at all, and Hermes' own `unknown` status,
which it stamps whenever its pricing produced no amount
(`agent/usage_pricing.py:549`, persisted into the usage table by
`agent/turn_usage.py:236,257`). Every child served through a custom gateway
provider carries that status, because Hermes prices only the routes it has
rates for. A row where the host did record an outcome — `included`, a billed
zero, any word it chose — keeps that figure untouched, and in a session whose
rows mix the two the recorded outcome is what the row reports. When the model
has no rate on either side, the row keeps rendering `$0.0000 (unknown)` rather
than gaining a figure OMH cannot support.

Every shipped rate carries the vendor page it was read from and the month, so
a reader can tell a current price from one that drifted.

A dispatch that inherits its provider is checked before the route is written:
if the session's own provider cannot serve the model being pinned — the
catalog records which provider families serve each model — the route is
refused, naming the inherited provider and which of your recorded or linked
providers could serve it instead. The check only refuses what is known
wrong. A provider neither recorded nor linked, a model the catalog never
described, and a multi-vendor relay (which serves every family) all leave
the answer unknown, and unknown dispatches unchanged.

A route is also refused when Hermes would not send the child where the route
says. OMH reads `config.yaml` and Hermes' managed config
(`$HERMES_MANAGED_DIR/config.yaml`, otherwise `/etc/hermes/config.yaml`),
which Hermes applies over it. It refuses in these cases:

- `delegation.base_url` is set and the route names a provider. Hermes'
  `delegate_task` then builds the child against that endpoint, with
  `delegation.api_key` (or the parent session's key) and `delegation.api_mode`
  (or a mode it detects from the URL), and takes only request overrides from
  `delegation.provider`. Two kinds of route still write. One is a provider
  Hermes resolves through its own SDK: `bedrock`, `vertex`, `google`,
  `google-genai`. The other is an endpoint Hermes itself names as the routed
  provider, when `delegation.api_key` is set: `https://api.anthropic.com` for
  `anthropic`, the Codex backend for `openai-codex`, and any other URL for
  `custom`. Without that key, the parent session's key goes to the endpoint,
  unless a credential pool for that provider serves it.
- The route names no provider, but `delegation.base_url` is set and the file's
  `delegation.provider` is one of those SDK providers. Writing the route
  removes that provider, so the child would move to the endpoint. Otherwise a
  route that names no provider writes: the child runs that model on
  `delegation.base_url`, which is the endpoint the person configured. The
  `status` action names it under `child_endpoint`: the file it comes from,
  its host and port, and the provider Hermes names the child.
- `model.base_url` is on a host other than openrouter.ai, anthropic.com and
  openai.com (or their subdomains), and `model.provider` is unset or `auto`.
  Hermes then sends an explicit delegation provider through its local-endpoint
  fallback, which resolves it as OpenRouter, or as the custom endpoint for a
  custom alias. `model.base_url` here is what Hermes reads after it moves a
  root `base_url`, a root `api_base` or a `model.api_base` into it, in that
  order, when the key is empty. A managed value replaces the person's value
  one key at a time, even an empty one. Some providers reach the same place
  with or without that fallback, so they still route: `openrouter`, `custom`,
  `moa`, `azure-foundry` and the Vertex names. `openai` is refused, because
  Hermes v0.21.1 to v0.21.3 send it through the fallback. A `model` section
  OMH cannot read safely counts as having that shape.
- The managed config sets `delegation.model`, `delegation.provider` or
  `delegation.reasoning_effort`, or gives `delegation` one value that is not
  null. Hermes would apply those values over the route, and a single value
  replaces the whole section.
- OMH cannot read one of the two files safely. That covers a repeated key
  (Hermes' loader rejects one), a merge key, a value continued past its line,
  and a block, tagged, escaped or `${VAR}` value. A `model:` or `delegation:`
  whose whole value sits on its line counts too when it is an anchor, a tag
  or a `${VAR}`. OMH reads a one-line flow mapping there
  (`model: {default: llama3, base_url: ...}`, the shape Hermes keeps when it
  saves such a section). That mapping is unreadable when it has a comment, a
  `?`, a repeated key, or a `key:` with no space after the colon. In the
  `delegation` section it also covers any line that is not a plain
  `key: value`, a comment, or a nested line under a key with no value. A
  value Hermes reads as unset (`''`, `~`, `null`, `false`, `no`, `off`, zero)
  counts as unset. For `model.provider` that holds only up to Hermes v0.21.3:
  from v0.21.4 Hermes keeps `false`, `no`, `off` and zero there as their text
  (`False`, `0`, `0.0`), a set provider, and the local-endpoint fallback above
  no longer applies. OMH still counts them as unset and refuses, which is
  what the older versions need. `''`, `~` and `null` read as unset on every
  supported Hermes. A spelling Hermes versions read differently is
  undecidable, like a value OMH cannot read: Hermes 0.21 reads `n` and `0e0`
  as text, and later versions read them as false and zero.
- `config.yaml` gives an alias (`*name`), `<<`, or a tag Hermes' loader
  cannot build (`!!merge`, a local `!name`, a verbatim `!<...>`; it builds
  `!!str`, `!!int`, `!!map` and the other standard tags) as a value in the
  `model` or `delegation` section, on its header line, on a nested line or
  inside a flow collection, or in a root `base_url`, `api_base` or
  `provider`. Hermes' loader fails on each of them, then uses its last good
  copy of the file, so every route is refused here, with or without a
  provider. OMH does not follow anchors, so it
  refuses a defined alias too. In the managed config the same values make
  their section unreadable and refuse as above: Hermes skips a managed file
  it cannot load, but OMH cannot tell that file from one whose aliases are
  defined.

Each refusal names the keys to change and changes none of them, in either
file. Restoring the person's own values is never refused.

An alias listed here dispatches as that provider's model; an alias not listed
dispatches unchanged with no provider, which is what a direct-billing host
wants — the file is optional and absent by default. A `provider` passed
explicitly with its wire `model` to `omh_delegate_route` outranks any stored
route. Provider and model change atomically; partial pairs and providerless
wire-shaped models fail before Hermes config is mutated. Fallback translates
an active exact provider/wire pair back to one alias. With no category passed,
it uses the one the conversation's own route was set under, and refuses when
the alias is not in that chain; with neither, it requires the category when
that alias has multiple chain origins. Validation is strict, token-only,
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
choice. CCAPI for Claude is preferred provider-family metadata only. It is
not a bundled or probed integration and is considered only when the user
declares the corresponding local route active. OMH never copies its tokens or
keys.

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
        "model_alias": "kimi-k3.1-pro",
        "model_family": "kimi",
        "preferred_provider_families": ["kimi-coding"],
        "reasoning_effort": "high",
        "reasoning": "Local editorial choice for this installation."
      }
    ]
  },
  "last_resort": {
    "any": [
      {
        "model_alias": "claude-opus-5-5",
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

Maestro is the external handoff boundary for Codex, Claude Code, the pi-family
runtime, OMC, OMX, and generic profiles. It projects an ordered eligible recommendation chain,
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

### External coding CLI handoff (claude-code / codex)

**Audience: agents and maintainers.** Normal users describe the goal to
Hermes in chat; the commands below are the backend surface that lets Hermes
(or an operator) discover and configure the Maestro external-handoff stack for
Claude Code and Codex. Discovery and configuration here are read-only and
never spend a token; the one exception is the readiness probe in step 2,
which runs a bounded no-op call against the CLI itself to earn the word
"observed." Order follows `EXTERNAL_CLI_PROFILES` in
`src/coding/executors.py`: claude-code first, then codex — neither is the
implicit default.

1. **Install and authenticate the CLI yourself.** OMH does not install, log
   in, or hold credentials for either CLI — that stays each CLI's own
   installer and login flow, run once outside OMH.
2. **Verify with a readiness probe, not a file check.**
   ```sh
   omh coding executor-readiness --executor claude-code
   omh coding executor-readiness --executor codex
   ```
   This is the honest evidence boundary the router itself holds
   (`READINESS_EVIDENCE_RULE`): *"A binary on PATH and an auth file are not
   run evidence."* A binary on `PATH` plus a local auth/config marker is
   `prepared`, not `observed` — the probe actually invokes the CLI (a
   `--version` or no-op call) and reads its configured model before calling it
   ready. Treat a `prepared`-only result as not yet ready.
3. **Optional: route per work category.** The Maestro lane resolves each
   unit's model from a category → model table (`ultrabrain`, `deep`, `quick`,
   `writing`, ...). Override it per profile with
   `omh coding category-maestro set codex ultrabrain gpt-6.1-sol:xhigh`, walk
   it guided with `omh coding category-maestro interview` (the interactive
   `omh setup` offers this walk too), and inspect the effective table with
   `omh coding category-maestro show`. A unit declares its category
   (`omh coding run --category <c>`, or a `category` field on a fanout unit);
   an explicit `--model` always wins. See `docs/FANOUT.md`
   (Category-maestro).
4. **Optional: set a dispatch-model preference.** `omh coding fanout
   dispatch` spawns each CLI headlessly and falls back to a `--model` value
   only when a unit's prepared handoff routed no model at all. That fallback
   lives at `~/.omh/routing/dispatch-models.json` — seeded empty only by an
   explicit "yes" to the interactive setup's maestro question, given a
   `"claude-code": "claude-opus-5-5"` entry by the setup's provider question
   once a Claude Code subscription is confirmed and no entry exists (the head
   of the Maestro lane's Claude chain, a pinned id since 2026-10-13),
   otherwise operator-edited —
   (`omh_dispatch_model_preferences/v1`, a `profiles` map from owner to model
   string, e.g. `{"schema_version": "omh_dispatch_model_preferences/v1",
   "profiles": {"claude-code": "opus"}}`). Neither profile ships a shipped
   default; `"opus"` is documented here as the alias to use when the account
   does not serve the pinned `claude-opus-5-5` id the setup seeds, or when
   the entry should follow whichever Opus the client recommends. Claude Code
   resolves that alias to the provider's recommended Opus: Opus 5.5 needs
   Claude Code v2.1.280 or later, and Microsoft Foundry resolves it to Opus
   4.6 (official, code.claude.com/docs/en/model-config). A one-off
   run can skip this file entirely with `omh coding run --model <id>`, which
   always outranks it. See `docs/FANOUT.md` (Dispatch-model preference) for
   the full schema.
5. **Check what the CLI's own skills contribute to a handoff prompt.**
   ```sh
   omh coding executor-skills --profile claude-code
   omh coding executor-skills --profile codex
   ```
   Read-only and metadata-only: it reports the profile's locally *declared*
   skills (name, invocation string, role) that the Maestro lane arranges into
   a composed prompt — a discovered `SKILL.md` is evidence the file exists,
   never evidence the receiving agent loads or honors it.
6. **Know where routing sends the delegation intent.** Once a coding-owner
   choice for a run is explicit, the handoff is composed by the `ulw-maestro`
   skill — the skill-facing surface of the Maestro lane
   (`src/coding/maestro/`) described under "Hermes-native and Maestro
   ownership" above. `omh coding capability-snapshot` freezes the per-owner
   evidence a fanout dispatch requires before it will run, and `omh coding
   fanout dispatch` remains the one sanctioned execution surface: explicit
   per invocation, local-only, and it never merges (see Fanout: Parallel
   Split, Dispatch Bridge, and Merge Contract in `docs/FANOUT.md`).
   `omh_delegate_route`'s `~/.omh/routing/route-provenance.json` records only
   prepared routes, never dispatch or execution evidence.

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

Where it differs from `install.sh`, it differs because the platform does, or
because the two searches look in different places:

| Behavior | POSIX | Windows |
| --- | --- | --- |
| Default venv | `~/.local/share/omh/venv` | `%LOCALAPPDATA%\omh\venv` |
| Default command dir | `~/.local/bin` | `%LOCALAPPDATA%\omh\bin` |
| How `omh` is exposed | symlink | `omh.cmd` shim (a symlink needs Developer Mode or elevation) |
| PATH | hint printed | appended to the user PATH; set `OMH_ADD_TO_PATH=0` for hint-only |
| Python search | `python3`, `python3.14` to `python3.11`, `python`, then the Homebrew, python.org, pyenv, and uv interpreter directories | `py`, `python`, `python3` |
| uv's interpreters | found by that directory scan, before any download | listed through `uv python list` only after `uv python install` ran |

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
| OMH TUI (bare `omh`) | `termios` raw mode | Not attempted; bare `omh` opens Hermes' own terminal |

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
- It writes no display key and installs nothing into Hermes' terminal: bare
  `hermes` is stock Hermes, and bare `omh` opens the OMH TUI. An install made
  by an earlier version, which wrote `display.interface`, `display.skin` and
  `display.sections` and installed a status widget and skin files, is migrated
  once per config by the next `omh setup` or `omh update`, primary home and
  every bot profile alike: see
  [Returning `hermes` to stock Hermes](#returning-hermes-to-stock-hermes).
  `--no-omh-tui` is accepted and does nothing; setup and update ask no
  display question.
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
fallbacks, plugin enablement, the display release, or memory-provider
selection. Model-alias writes remain a separate preview-and-approval step.

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

### Returning hermes to stock Hermes

Earlier versions made bare `hermes` look like OMH: setup and update wrote
`display.interface: tui`, an OMH skin in `display.skin` and collapsed
`display.sections`, and installed the OMH status widget
(`tui-widgets/omh-status.mjs`) and the four skin files (`skins/omh*.yaml`)
into the Hermes home. The next `omh setup` or `omh update` takes that back,
in the same config write that carries the registration forward, once per
Hermes home (the primary and every bot profile), with the rules uninstall
uses:

| Case | Before | After |
| --- | --- | --- |
| A display key OMH's record says it wrote, unchanged since | `display.interface: tui`, `display.skin: omh`, `display.sections.*: collapsed` | removed |
| A value consent replaced | you had `display.interface: cli`, OMH wrote `tui` | `cli` put back |
| A recorded value you changed since | `display.interface: cli` after OMH wrote `tui`; `tools: expanded` | kept |
| An OMH skin, with or without a record (`omh theme use` set one without one) | `display.skin: omh-crimson` | `crimson` saved to `<omh_home>/tui/theme.json` (unless a theme is already saved there, which the output then names), then the key removed |
| The default skin, with or without a record | `display.skin: omh` | removed; no theme is saved: an empty store opens with the same sky, and a saved one would beat a theme a bot profile sharing the store picked |
| A display key with no record (an install older than the record) | `display.interface: tui`, collapsed sections | kept: nothing says OMH wrote them |
| Your own skin | `display.skin: ares` | kept |
| A key OMH's record names, or a skin no record names with a value that reads as an OMH name (any of its values, when it is set twice), in a YAML shape the editor does not handle (a quoted key or an anchor anywhere in the file, a flow or duplicate `display`, a dotted key, a key set twice, a tag, a BOM, including one right before a first-line `display:`). A key OMH's record names that is set twice never reads as yours: the reader takes the first value, and Hermes may resolve another | `display.skin: !!str omh-crimson` with a record; `display.skin: omh-crimson` beside a quoted key; `skin: ares` then `skin: omh-crimson` | left as it is and named in the output; the release is not recorded, so the next setup or update tries again |
| Any other value in such a shape: no record names it, and no value of it reads as an OMH skin name, including an OMH name the reader cannot see (a flow `display`, a tag or anchor on the value) | `display: {skin: mytheme}`; `display: {skin: omh-crimson}` with no record | kept, and the release is recorded; while the value cannot be read, no theme is carried and every OMH skin file stays, and the output does not say bare `hermes` opens stock Hermes |
| A `display:` or `display.sections:` OMH created | emptied by the release | removed |
| The status widget OMH installed | `omh-status.mjs` and its manifest | removed (a manifest left without its widget goes too) |
| A widget the manifest cannot vouch for, or a symlinked `tui-widgets/` or `skins/` holding an OMH file | — | kept, named once, in the output of the pass that records the release |
| A symlinked `tui-widgets/` or `skins/` with no file under an OMH name (a dotfiles directory) | — | untouched, nothing printed |
| Skin files OMH installed (by manifest, or byte-identical to the shipped file) | `omh*.yaml` and the manifest | removed, except the one `display.skin` still names, or every one while that value cannot be read (a flow, duplicate or dotted `display`, a second `skin` in the block, a tag or anchor on the value); a quoted key, an anchor or a BOM elsewhere in the file does not stop the read |
| A skin file you edited | — | kept with its manifest record, named once, in the output of the pass that records the release |
| Everything else OMH writes: skills, `plugins.enabled`, `memory.provider`, compression, `settings.omh_home` | — | untouched |

The theme for a bot profile whose `plugins.entries.omh.settings.omh_home`
names its own store is saved there; one that names none shares the primary
home's store. A profile that names its store only in its `.env` (`OMH_HOME`),
or in a setting shape OMH's reader refuses (a flow `entries: {omh: ...}`, a
`<<:` merge key, a tab), gets none carried. That includes a profile whose
`.env` named a store after setup wrote the primary's into its setting: the
same pass takes that setting back. OMH reads the names in a `.env`,
never the values, so it cannot tell which store that is, and the output
gives the `omh --omh-home <that home> theme use <name>` that saves it there. One
store holds one theme, so the first home on the run that
carries one keeps it (the primary goes first) and the output names any
other home's skin it did not carry. When the theme cannot be saved (the
store is not writable), that home's release waits: its display keys and
files stay, the output says why, and the next setup or update tries again,
while the rest of the pass, registration included, lands as usual.

It happens once, on the first pass that leaves no key in a shape the editor
refused. That pass records `display_released_at` beside the write record in
`$OMH_HOME/runtime/state.json`, and from then on no display value
in that config is read as OMH's: a skin you pick for Hermes later, OMH
palette or not, stays through every update, and uninstall leaves it too.
So does a skin file you put back for it: after the release, setup, update
and uninstall count a skin file as OMH's only by the manifest record the
release left, so a copy of a shipped file is yours.
The pass that does something says so, per home:

```text
  Hermes display: bare `hermes` opens stock Hermes; bare `omh` opens the OMH TUI.
    released display.interface, display.sections, display.skin
    removed the OMH status widget, omh.yaml, omh-amber.yaml, omh-crimson.yaml, omh-mono.yaml
    saved OMH theme crimson for the OMH TUI; `omh theme use <name>` changes it
```

While an OMH skin file stays because `display.skin` names it, or may name
it, the first line says that instead of naming stock Hermes.
`--dry-run` previews it and writes nothing. A home that is not registered
(one `--skip-apply` left that way, or a home or bot profile that opted out
with `omh uninstall --registration-only`) keeps its config as it is, since
registering is what carries the release. `omh update` still removes the
widget and the skin files its manifest records there, keeping the skin its
config names, and so does `omh setup` for such a bot profile; for the
primary home, `omh setup` registers it again and runs the release in the
same write.

### TUI Themes

OMH ships four palettes for the OMH TUI. They are part of the package, so
switching is instant and offline, and nothing is installed into Hermes.

| Theme | Skin name | Look |
| --- | --- | --- |
| `sky` | `omh` | Sky turquoise on deep teal. The default. |
| `amber` | `omh-amber` | Amber gold on deep bronze. |
| `crimson` | `omh-crimson` | Ember red-orange on deep crimson. |
| `mono` | `omh-mono` | Neutral grayscale with white accents. |

```sh
omh theme                    # arrow-key picker with a live colour preview
omh theme list               # plain listing, always (the scriptable surface)
omh theme use crimson        # select one directly (also accepts omh-crimson)
omh theme use crimson --dry-run
omh theme status             # the active theme, which source decided it, and where it is saved
omh theme glow off           # the working glow off in every later OMH TUI session (on, or alone to show it)
```

Bare `omh theme` opens a picker: up/down arrows (or `j`/`k`) move the cursor,
each theme paints a sample of its own palette as you pass over it, Enter
saves the highlighted theme, and `q`, Escape, or Ctrl-C cancels without
saving anything. It needs a terminal on both ends — with `--json`, a pipe,
`TERM=dumb`, `OMH_NO_TUI=1`, or on Windows (no `termios`), bare `omh theme`
prints the same plain listing `omh theme list` prints. `NO_COLOR` keeps the
picker but drops every escape sequence, naming the hex values as text instead.

Rules worth knowing:

- **The choice lives under the OMH home.** `omh theme use` writes
  `<omh_home>/tui/theme.json` and nothing else; it never touches Hermes'
  config or the Hermes home. A bot profile whose
  `plugins.entries.omh.settings.omh_home` names its own store keeps its own
  theme there: `omh --hermes-home ~/.hermes/profiles/<name> theme use mono`.
- **The OMH TUI reads it when it opens,** in this order: the saved theme;
  else an OMH palette Hermes' `display.skin` names (an install the release
  above has not reached yet, or a palette you picked for Hermes yourself);
  else `sky`. `omh theme status` says which of the three decided, and the
  `omh model-chains` picker paints with the same theme. `/theme <name>`
  inside the OMH TUI switches the open session only; `omh theme use` keeps
  it. The palette is measured against the terminal's background as the
  session opens, and `/theme auto|light|dark` chooses that background for
  the open session (see [The OMH TUI](#the-omh-tui)).
- **The launch look is saved in the same record.** `/theme` in the OMH TUI
  writes `launch` beside `theme` in `<omh_home>/tui/theme.json`, and
  `/glow` or `omh theme glow` writes `glow` there; each write keeps the
  others.
- **Bare `hermes` keeps its own skin.** `display.skin` is yours; OMH reads it
  only for the fallback above and never writes it.

## Bot Profiles

Hermes bot profiles (`hermes profile create`, Desktop bot chats) are fully
independent Hermes homes under `~/.hermes/profiles/<name>` — each with its own
`config.yaml`, skills resolution, and plugin directory. A registration written
only to the primary home never reaches them, which is why a bot chat can show
zero OMH skills while the default chat has the full set.

`omh setup` and `omh update` sync every profile automatically:

- an already-registered profile is refreshed to the running version — its
  plugin bundle, under the same manifest-checked refusals the primary home
  gets, and the same display release
  ([Returning `hermes` to stock Hermes](#returning-hermes-to-stock-hermes));
- a profile with no OMH bundle at all — including a bot created after
  install — gets the full bootstrap on the next `omh setup` or `omh update`;
- a deliberately unregistered profile (see below) is left alone.

"Registered" means the profile names any OMH-managed skills directory, not
the exact one this install would write today. A profile registered at
`~/.omh/skills` before the command install moved to its shared generation
pointer is still registered: it gets refreshed and carried forward, not read
as an opt-out and frozen on the generation it was installed at. Only a
profile naming none of them has opted out.

Registered at one of them, never two. A profile registered at
`~/.omh/skills` before the pointer existed used to keep that entry when the
sync added the generation pointer beside it. Hermes refuses a bare skill
name that resolves to two different files across `skills.external_dirs`,
and every generation refresh makes the two copies differ, so every OMH
skill present in both failed to load by name in that bot. `omh setup` and
`omh update` run from the installer-managed command migrate such a home in
the same config write that registers the pointer: the older OMH-managed
entry is retired, matched by real path the way Hermes resolves entries (a
spelling through `${VAR}`, `~`, a trailing slash or a symlink is the same
directory; an unset variable stays as written, as it does in Hermes, and a
relative entry is read under the home that names it, as Hermes reads it,
so `../.omh/skills` in `~/.hermes` is the older entry and the directory
the command runs from never matters),
the home ends up naming exactly one managed directory, and the update
prints the move (`Bot profile <name>: registration migrated from <old> to
<new>.`; `Hermes registration migrated ...` for the primary home). Only
OMH-managed directories are retired; a directory you registered yourself
stays where it is. A command that is not the installer-managed one (a
checkout, a pip or uv tool install) registers its own `~/.omh/skills` and
never retires the pointer, so it cannot move a machine backwards.

A generation's own pack, `<managed root>/generations/<id>/skills`, is never
registered: only the `current/skills` pointer is. An entry naming one (an
older `omh setup` wrote the running generation's pack after the pointer) is
the same files as the pointer on the day it is written and a second copy of
every OMH skill once the next update moves the pointer, at which point
Hermes lists no OMH skill at all. The installer-managed command's setup and
update retire every such entry, from the primary home and every bot
profile, whether the generation is still on disk or already collected, and
a home naming only one is migrated to the pointer rather than read as the
opt-out; `omh uninstall --registration-only` removes them too, along with
every spelling of an older managed directory the migration retires
(`${VAR}`, `~`, relative to the home, or through a symlink). Only
entries that name a directory under the pointer's own managed root, read
from the home that names them, match: a `skills` directory under some
other `generations/` directory stays, and a relative entry matches only
when it reaches the managed root from that home. On Windows an entry
rooted without a drive, such as `\omh\...`, is read on the home's drive,
whichever drive the command runs from. Entries are expanded in the running
command's environment, which a Hermes service may not share.
`omh doctor` reports a home that still names two managed directories on
disk, an older generation's pack beside the pointer included, as
`external_dir_ambiguity` (one row per affected profile) and
promotes the row's `run \`omh update\`` to its headline next action; the
update's own post-check re-reads every home after the write and warns in
the same words, as a warning line only -- the update's exit code does not
move. The pre-pointer copy left on disk at `~/.omh/skills` is never
deleted by OMH: no manifest records it, and on a managed install it backs
the always-retained `bootstrap-legacy` generation (the self-update rollback
target, see [Staged installer updates and recovery](#staged-installer-updates-and-recovery))
until `omh uninstall` collects the generations. Doctor reports it as
unregistered but retained (`external_dir_unregistered_copy`), and only a
copy that no home registers and no generation links is named, with its
directory mtime, as safe to delete.

`omh uninstall` is symmetric with the sync. A full uninstall from the primary
home (`omh uninstall`, `--all`, or `--purge`) clears its bot profiles'
registration, reverses the same
`config.yaml` keys the primary home's reversal takes back, and removes its
managed artifacts — the plugin bundle, and any status widget or skin files an
earlier version left — through the same manifest checks the primary home gets: a profile directory OMH cannot
prove it owns is kept and reported, never deleted blind. The skin file
`display.skin` still names stays, after the release only a manifest record
proves a skin file OMH's (as on update), and a widget or skin directory OMH
must refuse, such as a symlinked one, is kept and named rather than ending
the uninstall. `--registration-only`
removes every OMH-managed entry from each profile — the same directories the
sync reads, so nothing is left behind for the next update to score as still
registered — while keeping their plugin directories, which is exactly the
deliberate opt-out state described below.

After a sync, restart Hermes Desktop so bot chats reload their skills.
A gateway that was running through the update keeps serving the bundle it
loaded at start. When Hermes' own records in a home (`gateway.pid` and the
`gateway-starts.log` ledger) show a last recorded start earlier than that
home's bundle install, the update names it with the command that reloads
it: `hermes gateway restart` for the primary home,
`hermes --profile <name> gateway restart` for a profile. That is file
evidence only: the bundle stamp is rewritten by every update, so the hint
covers gateways whose last recorded start precedes this update, and a
gateway running without a pid record is not named.

To opt one bot out of managed skill registration, unregister that profile only:

```sh
omh --hermes-home ~/.hermes/profiles/<name> uninstall --registration-only
```

That removes every OMH-managed skills directory the profile's config named,
whichever one it was registered at. The plugin directory stays in place as
the opt-out marker; setup and update never re-register a profile in that
state.

Registration-only removes managed skill entries by real path, including the
primary skill store A even when the profile selects a different runtime store B.
It also recognizes a configured runtime store's managed skills candidate; an
arbitrary external directory is never owned just because its basename is
`skills` or `omh`. It preserves store data, plugin files and plugin enablement:
it does not disable the plugin. Desktop mounting must be observed separately.
The remaining plugin directory plus absent managed registration is the opt-out
marker; the next sync leaves that profile unregistered.

OMH workflows are skill triggers, not Hermes slash commands, so they do not
appear in the `/` autocomplete — in any chat, bot or default. Invoke them as
`$ulw …`, `$plan …`, `$research …` (or plain phrasings like `ulw work …`),
and list what is installed with `/skills`. OMH adds no `/` entry to bare
`hermes`. In the OMH TUI that bare `omh` opens, `/omh-model` is the
per-category model-chain picker, the same one `omh model-chains` opens in
any terminal; it edits the store the `omh` that opened it resolved, so
`omh --hermes-home ~/.hermes/profiles/<name>` reaches that bot's own store
when the profile names one (`plugins.entries.omh.settings.omh_home`), the
same file the bot's delegations read, and it says which file it saved to.
Earlier versions registered `/omh-model` in Hermes' Modern TUI through the
status widget; it left bare `hermes` with the widget.

![The /omh-model chain picker: the same rows and keys as the CLI picker, over the transcript](../assets/omh-model-tui.png)

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
The default is `auto-safe` memory: Hermes remembers durable facts itself
through `omh_memory(action="capture")`, a locally safe summary is approved
at once and recalled from the next turn, and nobody has to run an approval
command. Credentials, raw logs, full transcripts, short-lived PR/commit IDs,
relative-time phrases, duplicates, and temporary task progress are held for
review or refused instead. Operators can choose:

```sh
omh setup --memory-mode off
omh setup --memory-mode review-first
omh setup --memory-mode auto-safe
```

A mode passed with `--memory-mode` is recorded as explicit and kept; a
profile that only stored the earlier `review-first` default follows the new
default on its next read (`omh memory status` shows `mode_source`).
`review-first` holds every capture for `omh memory approve`. This is OMH
project memory under `.omh/memory/`; setup does not mutate Hermes global or
internal memory.

The default user scope uses `~/.omh` and `~/.hermes` when no binding overrides
them. `--hermes-home <profile>` alone can select that profile's configured
store; it does not imply a private store. An explicit `--omh-home` selects
the requested store but never bypasses uninstall's shared-reference guard.
Use project scope when one repository needs isolated local skills and config:

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

### Build identity

`omh --version` and `omh doctor` both name the code behind the command that
actually ran, because the semantic version alone cannot tell two same-version
checkouts apart:

```text
omh 2.0.1 (source 6da2a3ca, clean)
omh 2.0.1 (editable 6da2a3ca, dirty)
omh 2.0.1 (build identity unavailable: installed package, no stamped identity)
```

`omh doctor` prints the same line, and `omh doctor --json` carries the full
`build_identity/v1` block: semantic version, install kind (`source_checkout`,
`editable_install`, `installed_package`, `standalone_artifact`, `unknown`), the
resolved command path, identity status, identity source, the full commit SHA,
dirty state, a reason when identity is unavailable, and a claim boundary.

Read the fields with these boundaries in mind:

- The revision is resolved from the running package's own source location, not
  from the caller's working directory, and only from a repository whose
  `pyproject.toml` declares this project. A wheel installed into a virtual
  environment inside somebody else's checkout therefore reports `unavailable`
  instead of borrowing that project's revision.
- Only identity is serialized. No branch name, remote URL, diff, changed-file
  list, or environment data appears in either output.
- Dirty state is `unknown`, never guessed, when the revision came from reading
  `.git` directly because no `git` binary was available.
- Published OMH artifacts carry no stamped identity today, so a wheel, npm, or
  Homebrew install reports `unavailable` with `no_stamped_identity`. That is
  the explicit compatibility result: a packager that ships a
  `build_identity_stamp/v1` `_build_identity.json` inside the package is read,
  and an artifact without one is never given an invented revision.
- The block is diagnostic provenance only. It is not evidence that the named
  revision was tested, reviewed, passed CI, was published, or behaved
  correctly at runtime, and it never changes the doctor status or exit code.

Plugin support is installed by `omh setup` by default. It provides a thin
Hermes plugin bridge in addition to the skill pack:

That installs `~/.hermes/plugins/omh` with deterministic workflow
recommendation, metadata-only HUD/status/role support, and a bounded evidence
probe.
`omh hud` prints the same compact status line a plugin surface can render. It shows only operationally useful status: OMH version, plugin
readiness, target topology, the coding-agent segment described below, and
evidence state. Skill counts, setup inventory, token metadata, and deep
diagnostics are left to `omh doctor`, `omh_status`, and machine-readable HUD
JSON.

The HUD payload also carries a metadata-only plan todo list. When a todo is
declared — by Hermes through the `omh_todo` plugin tool, or by an agent or
operator through `omh runtime todo set` — the OMH TUI that bare `omh` opens
renders it as a compact checklist above the composer (its agent view stands
under the info line), and the Hermes Desktop pane draws the same payload. Bare `hermes` draws
neither.
`omh runtime todo show` prints the todo projection the HUD payload carries
(`todo` plus `display.todo_lines`), and `omh runtime todo clear` removes it. Todo items are plan declarations, never execution, review, CI, or
merge evidence; an all-done list collapses to a single header line and a list
untouched for 24 hours is hidden as stale.

Hermes' own checklist tool, `todo_list`, reaches the same panel. Wherever it
is present — in the session's tool list, or found through `tool_search` — it
holds the steps, and the plugin's `post_tool_call` hook mirrors each
successful `todo_list` write into the session's plan todo, so one plan shows
whichever tool holds it and the model never writes the same list twice. A
native `completed` is still a declaration, and a `cancelled` item shows as
skipped. `omh_todo` then carries only what `todo_list` cannot: `plan_stage`
on a planning run, the completion dossier, an item's `blocked_reason` and
the plan's `deferred_reason`; on a plan `todo_list` holds, `todo_list`
alone sets item states. A planning checklist awaiting acceptance and a
`code-story` plan stay with `omh_todo` while open, and an accepted plan until
it goes stale; a native write replaces none of them, `omh_todo action=clear`
is how a session leaves one for unrelated work (a recorded `deferred_reason`
only pauses it), and the session's next turn is told once when a `todo_list`
write was not mirrored and the plan is still held and not deferred. Hermes
Desktop draws a `todo_list` itself (the composer's status stack), so for a
plan `todo_list` holds the Desktop pane does not repeat its items: it shows a
compact "in todo_list" plan summary only when OMH knows something Hermes
does not show — an item waiting on a recorded reason, or a checklist
unchanged past the stall threshold. The OMH TUI's plan panel draws the items
whichever tool holds them: the done ones quiet (a `✓` in the done colour,
their words muted) and, when they do not all fit, folded into one `✓ N done`
row before any item still to do is cut. Ctrl+P folds the plan to its header
and the item it is on (`[Plan] │ 6/7 ▸ <item>`), or expands it again, for the
rest of the session; the header says `ctrl+p fold` or `ctrl+p expand` on its
right where there is room.

A plan may be declared from a named phase template instead of from phases the
model writes out itself. `omh_todo` with `action=set` and
`template: code-story` declares the ten phases of a code story — `I. Story`,
`II. Implement`, `III. Review`, `IV. QA`, `V. Fix`, `VI. Manual test guide`,
`VII. Deep guide`, `VIII. ELI5`, `IX. Quiz`, `X. Close` — in delivery order,
and stores the template name on the record. Every later write to that record
is held to the same coverage, so a phase cannot quietly leave the plan: a
change that needs no manual test guide carries that phase as `state: done`
with a `blocked_reason` saying why it does not apply, and the panel renders
the row as `[✓] … (skipped: …)`. Both plan headers count them — a running
plan reads `Todo · story   5/10 (3 skipped)`, a finished one
`Todo · story ✓ 6/10 (4 skipped)` — because the summary line is all that
survives once the item rows collapse, and only the finished form subtracts
the skips from its numerator. A `set` without `template` declares an
ordinary plan exactly as before, and nothing infers the template from what
anyone typed — the argument is the whole of the declaration.

Two bounds worth knowing before declaring one. The template is a plugin-tool
surface only: `omh runtime todo set` has no `--template`, and a CLI `set`
over a stamped plan replaces the record and un-stamps it, the same way a
plain `omh_todo` `set` does. And the ten phases spend half the 20-item cap, so
a story plan has ten slots left for subtasks across all ten phases. The
twenty-first item is refused, not truncated, and the whole write is lost with
it — nothing partial lands and the record on disk is untouched. A stamped plan
is told which bound it hit: `todo items are capped at 20; template
'code-story' declares 10 of them, leaving 10 for items of your own, and this
plan has 21. Nothing was written.` A plan that named no template reads the
plain `todo items are capped at 20`, as it always has.

The panel belongs to the session that declared the plan. When Hermes
declares a plan through `omh_todo`, the record is stored for that session
(`$OMH_HOME/runtime/todos/<session key>.json`) and read back only for it: the
OMH TUI names the session it shows on every poll, the Desktop pane its
focused session, and the plugin tools (`omh_todo`, `omh_hud`) and the pre-LLM
reminder name the session Hermes dispatched them for — never one named in
tool arguments, so a model cannot address another session's record. A plan declared from a Slack or Discord gateway session,
or from a second TUI open at the same time, is its own record, so it neither
renders in another session's panel nor overwrites that session's checklist.
Per-session records are pruned on write once they pass the 24-hour stale
bound; nothing else in that directory is touched. `omh runtime todo set|clear|show --session
<id>` addresses one session's record from the command line.

Records written without a session id — `omh runtime todo set` with no
`--session`, or anything predating the field — are the home-wide
`$OMH_HOME/runtime/todo.json`, scoped by write time instead: a plan written
before the reading session started belongs to an earlier one and reads as
stale. That fallback only applies where the host can answer it. With no
`$HERMES_HOME/state.db`, an unreadable one, no live TUI session recorded in
it, or a reading session it does not list as a TUI (a gateway session has no
row to date the record against), the projection keeps the age-only behavior
above and shows the plan, since hiding a legitimately current checklist on
missing evidence is the worse failure.

A TUI session reference (`tui_session_ref`, which the Desktop pane passes
for its focused session) has one alias, which the reader resolves: it can
be the durable session key, or, for a freshly created session, the
gateway's transport id, which no record and no `state.db` row carries. The
host's active-session lease registry
(`$HERMES_HOME/runtime/active_sessions.json`) is where the two names for one
session meet — it records both against one lease — so a reference that
names no live TUI row is looked up there and read as the session it belongs
to. Each surface therefore renders the plan its session declared and no
other's, whether that session was created or resumed.

The host claims a session's lease on its first real turn rather than at
creation, so a TUI nobody has prompted in is named by no entry — and it has
declared no plan either, so its empty panel is the same answer. A reference
the registry does not pair keeps its own identity and falls back to the
home-wide record under the gates above; it never adopts another session's
record. The plugin tools and the reminder are unaffected either way, because
Hermes dispatches them with the durable key.

The verification verdicts, review finding sets and QA results a session
declares through `omh_todo action=record` are a separate record from the
plan: the completion store at `$OMH_HOME/runtime/completion/records.json`.
`omh runtime verdict show [--session <id>] [--checkpoint <id>] [--revision <r>
--environment <e>]` reads it from the command line. `store_state` says whether
the store is absent, empty or present; each row keeps the evidence state its
writer claimed under `standing: model_declaration`, `observed: false`; and
freshness is judged only against a revision and environment you pass, `unbound`
otherwise. It writes nothing. The record shape and the reading rules are in
`docs/HARNESS_QUALITY.md` under Declared Verdicts.

Native agent activity is a separate ownership policy from todos. A mapped
valid durable identity selects native `state.db` children before row limits
and totals, following only the compaction continuations Hermes itself links
(the same rule the route restore and `omh_team` read), never a branch, a
reset, a `tool` session or a delegated child. Missing, invalid or unmapped
identities retain
the previous global native fallback, including best-effort manifest context.
The OMH TUI is the one exception: it names the durable key the gateway handed
it, and Hermes writes that key's `state.db` row on the session's first prompt,
so until then a fresh session owns no children and its panel lists none rather
than another conversation's.
The header line marks `[global]` whenever rows from outside this conversation
are in the list, so no surface attributes those totals to this chat.
It is one marker for one fact, not a description of the list: an entirely
unowned list and a mixed one both carry it. A session-only list carries no
word at all, because each row already carries what runs it: `[sub]` for a
delegate_task child, `[bot]` for a Kanban board worker. Mapped native rows omit
unowned manifest/route labels. OMH executor, Maestro and DAG activity remains
on the panels, explicitly global. This changes display attribution
only, not delegation or the todo policy above.

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

That version is the **installed** version, never the newest published
release: it is what `omh --version` prints, and for the readers inside
Hermes' interpreter (the Desktop pane, the plugin's tools) it is the version
`omh install`/`omh update` recorded, because they load the plugin-bundle
reader without being able to import the `omh` package. A machine that has
not run `omh update` since a release keeps showing the version it installed,
and an already-open OMH TUI keeps showing it until it is reopened. See [Release](RELEASE.md), "After the Cut".

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
`--observe-local-processes` is supplied.

One reading costs about 0.7 s of wall time, most of it interpreter start and
importing the CLI, so the helper does not take one every 8 s regardless. It
polls at the `--interval` cadence while the menu keeps changing, and each
consecutive reading that renders the same menu doubles the gap up to a ceiling
of 60 s; any change drops it straight back to `--interval`. Between readings a
2 s timer stats the paths the payload names in `watch_paths` (Hermes'
`state.db` and its write-ahead log) and reads as soon as one moves, so a
session starting shows up within one `--interval` plus a tick however long
the machine has been idle. That wake never reads sooner than `--interval`,
because a live session writes its store every few seconds and an unfloored
wake would read on every tick; a busy machine therefore costs exactly what
it cost before this backoff existed. A change only the process scan can see,
such as a Hermes process that has not touched its session store, waits for
the next scheduled reading instead. Setting `--interval` higher than 60 s keeps that
cadence; the ceiling never polls faster than you asked for.

Use explicit commands when you want to manage it yourself:

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

### Picking work up on another surface

Audience: users first, then wrapper and plugin maintainers. People do not call
the tool; they say "continue what I was doing" in the TUI, Desktop, or a chat
thread, and Hermes calls `omh_resume`.

`omh_resume` reads the person's earlier work in this profile: each plan todo
another of their sessions declared in the last 24 hours, with its item states,
and each completion checkpoint one of those sessions froze in the last 30
days. It joins them to Hermes' own `state.db` rows for the surface, when the
session was last active, its tool-call count, and its repository name and
branch, and renders plain text newest first in the `text` field. It writes
nothing and adds nothing to any other turn.

Who is "the same person" comes only from those rows, never from the message:

- Every local surface (`cli`, `tui`, `desktop`, `acp`) is the profile's own
  user, so the TUI and Desktop see each other's plans.
- A chat-platform session counts only in a direct message: the calling row's
  `source` and `user_id` with `chat_type` `dm`. A Slack user sees their own
  earlier Slack direct messages and no one else's, which matters because one
  gateway profile serves many people. A group channel or thread is refused:
  its row names one user while anyone in the room can ask, and everyone there
  would read the answer.
- Hermes records no link between a platform user and the local user, or
  between one platform's user and another's, so those crossings are not made.
  Hermes' own `/handoff` moves a whole session to a platform when that is what
  the person wants.
- A surface that names no person (webhook, cron, a delegated subagent
  session, a shared chat), a session `state.db` does not list yet, or an
  unreadable `state.db` gets a plain statement that nothing is shown, never
  another person's work. Delegated subagent sessions and sessions the person
  archived or hid are not listed as earlier work either.

A plan whose declaring session this profile's `state.db` does not list is
never shown, so two profiles sharing one OMH home stay apart. The summary is
metadata only: no session title, activity description, deferral reason or
transcript. Plan item text that looks like a credential is redacted before
it is relayed. Items marked done are that session's declarations, not observed
results, and the text says so.

## Install Path A: Hermes-Native Skill Tap

Use this path when the target Hermes environment supports skill taps:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

Use the full identifier for every tap install. A short name can resolve to
another tap's skill in current Hermes CLI releases. The router skill's directory
and its frontmatter name are both `omh-routing`.

Path A is an alternative to `omh setup`, not an addition to it. A tap install
lands in the Hermes home's own skills directory, which Hermes 0.21.6 and later
rank above the `skills.external_dirs` entry OMH manages, so on a machine that
also runs `omh setup` the tap copy hides the managed skill; older hosts refuse
the shared name as ambiguous instead. Either way the tap copy never receives
an OMH update. `omh doctor` names such a copy under `identity_conflicts`.

Install additional workflow skills when you want direct Hermes skill surfaces:

```sh
hermes skills install rlaope/oh-my-hermes/skills/ulw-interview --yes
hermes skills install rlaope/oh-my-hermes/skills/ulw-plan --yes
hermes skills install rlaope/oh-my-hermes/skills/ulw-research --yes
hermes skills install rlaope/oh-my-hermes/skills/omh-code-review --yes
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
omh release evidence-bundle --version 1.0.5 --write --repo-root "$PWD" --json
omh release evidence-bundle --version 1.0.5 --verify --repo-root "$PWD" --json
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

Use the evidence bundle when you want that local release-candidate evidence
written under `.omh/runtime/release-evidence/` for a release PR or release note:

```sh
omh release evidence-bundle --version 1.0.5 --write --repo-root "$PWD" --json
```

The bundle is not CI, live Hermes smoke, executor, delivery, merge, or GitHub
release evidence.

#### Revision-bound evidence and `--verify`

Maintainer and release-automation surface. Nobody installing or using OMH needs
to run any of it.

The bundle used to record what the gates said without recording which source
they said it about. Attached to a release, that reads as provenance for whatever
the reader assumes. It now binds to a revision, and the binding can be re-checked
without regenerating anything.

`--repo-root` names the checkout being described. OMH reads it only, never
writes to it, and records the full commit hash, the full tree hash, whether the
worktree was dirty, and a deterministic input manifest of repo-relative paths
and `sha256:` digests. Absolute paths never land in the file, and the recorded
artifact is stored by basename.

Re-check a recorded bundle with:

```sh
omh release evidence-bundle --version 1.0.5 --verify --repo-root "$PWD" --json
```

Verification is pure. It never writes and never regenerates, so a run that
disagrees with the bundle cannot silently repair it. The verdict is one of a
closed set, and exit code 0 means `matching` and nothing else:

| Verdict | Meaning |
| --- | --- |
| `matching` | Same commit, same tree, digests agree. The only exit-0 verdict |
| `dirty` | The worktree has uncommitted changes, so no clean claim is possible. Checked first and it wins over `stale` |
| `mismatched_revision` | The recorded commit is not the one you are on now |
| `stale` | Same commit, but the tree, a declared input digest, or the artifact digest moved |
| `unverifiable` | Identity is unavailable on one side, so the answer is unknown rather than assumed |
| `legacy_schema` | A pre-v2 bundle. It can never read as `matching`, because it was never bound to a revision |
| `missing` | No bundle is recorded for that version |

`--write` is fail-closed the same way. Without a usable identity, meaning no git
checkout and no explicit `--archive-digest` or `--artifact-digest`, the bundle is
still written for local use but reports `status: needs_attention` and
`publication_ready: false`, and the command exits non-zero. It never quietly
passes.

Compatibility: this is a deliberate hard bump to
`omh_release_evidence_bundle/v2`. Bundles already on disk stay exactly as they
are and verify as `legacy_schema`; that is the point, since a v1 file genuinely
was not revision-bound. The evidence index stays at v1 and only gains
`commit_sha` and `tree_sha` alongside what it already had. Release publication
regenerates the bundle from the exact tagged checkout and refuses to publish
when the binding does not hold; see [Release](RELEASE.md) and
[Distribution](DISTRIBUTION.md) for the maintainer flow.

What this proves is provenance for the recorded revision. It is still not CI,
live Hermes smoke, executor, delivery, merge, or GitHub release evidence.

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup
```

The live smoke runs the selected install path and then verifies:

```sh
hermes skills tap list
hermes skills list --enabled-only
hermes skills check omh-routing
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
itself, because `omh` makes no network calls of its own. A later `omh setup`
records the release from what is installed: pip writes the exact URL it
installed into the package's PEP 610 `direct_url.json`, and setup reads the
channel, version, and source ref from that. A release wheel or tag archive
records `stable`; the `main` archive or a commit (a SHA-pinned archive, or
`pip`/`uv tool install git+...@<sha>`) records `preview` with that commit as
the source ref. npm, Bun, and Homebrew installs record the package version and
no channel, since the package manager owns that. Any other recorded URL, such
as a fork or a local wheel, is recorded as the package URL with no channel.
Pass `--channel`, `--version`, or `--package-url` to `omh setup` to name one.

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
steps, an `operator_summary` block, and a `hermes_native_setup/v2` block that
names the equivalent Hermes skill install path, managed skill directory, and
`skills.external_dirs` registration key. v2 marks the payload that no longer
carries the branded-TUI fields v1 did (`tui_verdict`, `steps.tui_widget`,
`steps.skin`, `steps.hermes_tui_preflight`, and `steps.apply.tui_interface`,
`skin` and `display_sections`); `steps.apply.display_release` reports what
the release took back.
`hermes_native.observed` means the local bootstrap/apply step actually ran; it
does not prove Hermes has reloaded or used the skill yet.
`discovery_status: config_registered_reload_required` means restart or refresh
Hermes before claiming the skill is visible in chat.
`omh doctor` should report a grouped health summary by default: managed skills,
runtime state, Hermes registration, target topology, optional surfaces, command
availability, issue counts, recommended next action, and the `last_doctor`
state-log entry when the runtime directory is writable. `omh doctor --json`
returns the full check payload plus `doctor_summary/v1` and `build_identity/v1`.
`omh list` should show a concise managed skill summary plus workflow lanes by
default. `omh list --json` returns the managed manifest plus
`omh_installed_skill_catalog_context/v1` and per-skill descriptions, routing
hints, examples, and evidence boundaries.
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
   Claude Code and generic agents use prompt-only handoffs; Hermes, OMX, the
   pi-family runtime, and OMC use runtime handoffs with team/swarm,
   worker-protocol, and worktree guidance. The wrapper records only what it
   actually observes.
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
omh docs workflows --installed
omh harness list
omh harness inspect planning
omh harness validate
```

`omh docs workflows --installed` renders the same reference narrowed to the
skills the local install manifest records; it needs an install, and it cannot
be combined with `--json` or `--check`.

Use `omh runtime export --redacted` when you need a portable support artifact.
Exports redact prompt, response, token, secret, key, and password-shaped fields by
default while preserving proof fields such as run status, event names, observed
delegation flags, and wrapper completion status.

## What Gets Recorded

`omh` records runtime metadata only by default:

- setup/install/apply/doctor summaries in `~/.omh/runtime/state.json`,
  including `release_source_commit` -- the comparable remote `main` identity
  `omh update-check` compares against, recorded only on the preview channel
  and only when update-check is not `off`
- workflow run envelopes in `~/.omh/runtime/runs/<run-id>/run.json`
- append-only run events in `events.jsonl`
- append-only lifecycle observations in `~/.omh/runtime/journal/events.jsonl`
- wrapper chat sessions in `~/.omh/runtime/wrapper_sessions/<session-id>/`
- delegation observation in `delegation.json`
- prepared coding handoffs in `coding_delegation.json`
- wrapper observation in `wrapper.json`
- review, CI, and merge evidence in `review.json`, `ci.json`, and `merge.json`
- paper-learning cards and chunk ledgers in
  `~/.omh/paper-learning/<paper-id>/card.json` and `ledger.jsonl` (see
  [Paper reading progress](#paper-reading-progress-agent-reference))

Prepared handoff is never treated as implementation, review, CI, or merge
evidence by itself. If the wrapper cannot prove that a step happened, status
should stay `prepared_not_observed`, `not_observed`, or `not_available`.

### Paper reading progress (agent reference)

The `paper-learning` skill explains a supplied paper section by section and
ends each chunk with covered / next / missing. `omh paper` is the store that
carries that ledger across Hermes sessions; Hermes runs it for the user, who
asks in chat ("explain this paper, pick up where we left off").

```sh
omh paper plan --title "Attention Is All You Need" --source ./paper.pdf --level expert
omh paper progress <paper-id> --covered Abstract --covered Introduction --next Method
omh paper list
omh paper show <paper-id>
omh paper validate
```

- `plan` writes `paper_learning_card/v1` to
  `$OMH_HOME/paper-learning/<paper-id>/card.json`. A `--source` that names a
  local file is recorded with its absolute path, size, and SHA-256 so a later
  session can tell it is the same bytes; the file is never parsed. The size is
  read before the bytes, a file above the 256 MiB hash budget records
  `hash_skipped: over_budget` instead of blocking, a file that changes while
  it is being hashed is refused, and a file that cannot be read refuses the
  plan with `source_unreadable` and writes nothing. A URL or a reference such
  as `arxiv:1706.03762` is recorded as text. `--level` accepts the four
  contract levels and their aliases and refuses anything else rather than
  recording `choose`. `--section` (repeatable) replaces the ten default
  sections and must not be empty; `--source-state`, `--observed-section`,
  `--missing-section`, and `--evidence-ref` record what a host already
  observed.
- `progress` records one explained chunk: `--covered` sections become
  `explained` in the coverage ledger, `--missing` sections become `missing`,
  `--next` names where to resume (default: the first pending section), and
  `--note` keeps a short resume note (500 characters at most; the explanation
  itself stays in chat). Explaining a section is not the same claim as having
  seen its text: `--covered` never moves the card's `source_state`. Only
  `--observed-section` and `--source-state` do, and on this path both need
  `--evidence-ref` (or one already on the card). A section recorded missing
  cannot be covered until the same call records it observed. Each call
  appends one line to `ledger.jsonl` and then rewrites the card, both under
  one lock, so concurrent chunks serialize; the ledger is the history and the
  card its projection, so a failure between the two writes leaves the history
  complete and the card one chunk behind, which `validate` names. Section
  names must already be in the ledger; a typo is refused rather than becoming
  an eleventh section.
- `list` and `show` print plain text by default with the reading status
  (`not_started`, `in_progress`, `waiting_for_missing_sections`,
  `complete`), the covered and missing sections, and the next section.
  `list` orders records by their recorded creation instant (two plans in one
  second keep the order they were recorded), shows the latest 20 and says so
  when more exist; a linked directory under the store is skipped, the way
  `show` refuses its id. Pass `--json` or set `OMH_OUTPUT=json` for the full
  payload.
- `validate` exits 1 when a card fails its schema, a ledger line does not
  parse, a directory name disagrees with its `paper_id`, or the ledger length
  disagrees with the card's `progress_count`. A record `list` cannot read is
  counted and named in `unreadable_records` rather than dropped, and `show`
  or `progress` on one reports `record_corrupt` (as opposed to
  `record_not_found` for an id that has no record) instead of a traceback.

What the store proves is where reading stopped and which bytes the source
had. PDF extraction, page counts, figure OCR, citation checks, and the
correctness of an explanation stay `not_observed` until a host records them;
the card keeps that list and every JSON payload carries the same boundary.

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
  `omx-runtime` / `pi-family-runtime` / `omc-runtime` return a
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
- `omh memory apply --batch <file>` is a compatibility report: it returns
  `review_required` and never writes. Reviewed scope updates go through
  `omh memory batch-stage`, `batch-review`, and `batch-apply --apply`, which
  writes only under `.omh/memory/`.
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

### Staged installer updates and recovery

Applies to installer-managed commands only: the curl installer, the PowerShell
installer, and any install whose `omh` launcher lives under the managed root
(`~/.local/share/omh` on POSIX, `%LOCALAPPDATA%\omh` on Windows). Homebrew, Bun,
and npm installs keep delegating to their own package manager and are untouched
by everything in this section, as are pip, pipx, distro, and source-checkout
installs.

An installer-managed `omh update` no longer upgrades the running environment in
place. It runs as a transaction:

1. Take an enforced lock. A second `omh update` on the same machine stops
   immediately with `another omh update is already in progress; no changes were
   made` rather than racing the first one.
2. Reconcile anything a previous interrupted run left behind (see below).
3. Stage the new release into a fresh generation directory, entirely separate
   from the one you are running.
4. Smoke-test the candidate: import the package, read its version, render its
   workflow pack.
5. Move the `current` pointer to the candidate. This is one atomic rename and it
   is the only step that makes the new version visible.
6. Re-enter through the pointer to confirm the activated version actually runs.
7. On success, keep the previous generation as the known-good fallback and
   collect the rest. On failure, attempt to move the pointer back and re-enter
   the previous generation; shared-resource restoration must succeed before
   recovery is considered complete.

The pointer makes the command/workflow-pack selection atomic, not all shared
resource changes. Both things that consume the
install are spelled beneath it and never in resolved form: the `omh` launcher
resolves through `current/venv/bin/omh` (`current\Scripts\omh.exe` on Windows),
and the workflow pack Hermes reads is registered in `skills.external_dirs` as
`current/skills`. Because both names stay fixed, the command you run and the
pack Hermes serves always come from the same generation. There is no observable
moment, including a crash mid-update, where you get the new command with the old
pack or the reverse.

On disk, under the managed root:

```text
current -> generations/<id>     # the single activation pointer
generations/<id>/venv           # that generation's command environment
generations/<id>/skills         # that generation's workflow pack
self-update.json                # private activation state (self_update_state/v1)
venv/                           # the pre-generation environment, kept as fallback
```

What you see when something goes wrong:

| Situation | What happens | What you get back |
| --- | --- | --- |
| Staging or download fails | Candidate deleted before anything is activated | The install you already had, untouched |
| Candidate fails its smoke checks | Candidate deleted before activation | The install you already had, untouched |
| Activated version fails the post-activation run | Attempt pointer rollback and restoring reentry | Previous command/pack selected if rollback succeeds; shared resources restored only if reentry succeeds |
| Restoring reentry also fails | Retain recovery marker and candidate anchor; report failed restoration | Recovery still required, not a healthy restored install |
| Machine dies mid-activation | Next `omh update` reconciles the marker and retries the required activation/restoration step | Command/pack remain paired; restoration can still fail |
| Two updates at once | The second refuses to start | No partial work |
| You want the previous version back | `omh update --recover-known-good` selects and checks a retained generation | Restoration is reported only after its reentry succeeds |

When candidate activation fails and restoring reentry also fails, the persisted
`activation_in_progress.restore_required` marker remains true and records the
candidate/previous anchors. JSON reports `rollback.status: failed`, an empty
`rollback.restored`, and `recovery.status: required` / `action: restore_failed`,
with the failure reason. Do not delete the retained candidate or clear the
marker by hand. Preserve the reported paths and failure evidence, resolve the
reported restoration error, then retry `omh update`: pending restore intent
allows only restoration until it succeeds, not a fresh candidate activation.
A healthy restoring reentry clears the marker and permits candidate cleanup;
the original attempted update still reports failure rather than success.
Pointer rollback alone does not prove shared-resource restoration or reverse
all user/plugin state. Run `omh doctor` after recovery and inspect any remaining
profile failures before treating the install as healthy.

`omh update --recover-known-good` refuses rather than guesses when no retained
generation exists. If the activation state file is unreadable or carries a schema
this version does not know, the update fails closed, names the file, and points
at that same recovery flag instead of rewriting it.

Installs made before this layout existed migrate lazily, and only once. On the
first staged update, after the candidate has passed its smoke checks, OMH creates
a bootstrap generation that links to the environment and pack you already have,
points `current` at it, retargets the launcher, and rewrites the Hermes
registration. Every step of that happens while both names still resolve to the
old pair, so an interruption anywhere in the migration leaves you on the version
you were already running. A candidate that fails staging or smoke never triggers
any of it. The pre-generation environment and the pack at `~/.omh/skills` survive
as fallback targets and are never collected while they are retained. You are not
asked to rerun `omh setup`, and `omh uninstall` collects the pointer, the
generations, and the state file through its normal dry-run and kept-file
reporting.

`omh update --json` reports the transaction as
`command_package_self_update/v1`, with a `phase` naming how far it got
(`staging`, `verification`, `migration`, `activation`, `post_activation`,
`recovery`, `cleanup`) plus `rollback` and `cleanup` records. `ok` is true only
after the post-activation run through the pointer succeeded, so a payload that
stops at an earlier phase is a report of what did not happen, never a claim that
the new version is live.

Windows: `current` is a directory junction, so activation and bootstrap links
do not require Developer Mode or an elevated shell. The `omh.cmd` shim is
atomically rewritten to the literal `current\venv\Scripts\omh.exe` path; it does
not name a resolved generation. Deterministic Windows seams cover activation,
rollback, junction-creation failure cleanup, bootstrap links, and the shim.
Live Windows behavior under real file locking remains **Not-tested**.

### Startup update check (opt-in)

By default, `omh`/`hermes` never checks for updates on launch -- OMH's core
promise is no network calls without an explicit opt-in. `omh update-check`
turns on a bounded, best-effort comparison against `origin/main` that runs
right before bare `omh` opens the OMH TUI. This is `omh`'s own launch door
(`commands/bare_launch.py`); bare `hermes` execs your Hermes install directly and
never passes through this process, so it never runs this check.

```sh
omh update-check status
omh update-check set --mode notify              # one-line notice when behind
omh update-check set --mode auto                 # runs `omh update` automatically
omh update-check set --mode off                  # shipped default
omh update-check set --interval-hours 12          # default is 24, 1-8760 accepted
```

Interactive `omh setup` asks this once, as its last question, and writes
whichever mode you pick. `off` is the pre-selected answer, so pressing Enter
through the wizard installs exactly what a non-interactive install installs
and makes no network request. The question is settled by having been
answered, not by which answer: choosing `off` records `off` and setup never
asks again. `omh setup --yes`, `--json`, `--no-interactive`, and any run
without a terminal never ask and write nothing, which leaves the key absent
so a later interactive run can still ask. Changing your mind afterwards is
`omh update-check set`.

`notify` prints a single line such as `OMH update available: 3f2a1c9 ->
9b7e21d; run \`omh update\`` when the preview channel is behind `origin/main`,
and nothing when it is current; the line prints only for a launch that
actually ran a fresh probe, not for every launch that reuses the cache inside
the same interval. `notify` never blocks or delays the launch either way.
`auto` is different: it reuses `omh update` itself (never a reimplementation,
run as a real subprocess so its own re-entry sees a normal `omh update`
argv), and by design that means the launch waits for that subprocess -- a
command-package refresh can take minutes on the preview channel, the same
wait `omh update` always has. Because the launch is held for that whole
wait, `auto` says what it is doing. It prints one line before it starts:

```
OMH Auto Update: 3f2a1c9 -> 9b7e21d (preview channel); running `omh update`.
```

and one when the update lands, naming the version now installed:

```
OMH Auto Update complete: omh 2.0.1 is installed.
```

That completion version is read back from the record `omh update` just
rewrote, and the OMH TUI the launch opens next imports the updated package,
so the line names the version its banner will show. A failure
still prints `omh: update-check auto-update failed` on stderr and nothing
else changes. `off` and `notify` never print either line. A non-blocking lock
keeps two simultaneous launches from auto-updating at once -- the launch that
loses that race prints nothing, because it ran no update -- and a failed or
already-applied attempt is never retried before the next interval.

Either mode spends at most one curl
subprocess per `interval_hours`, carrying two requests: the conditional,
ETag-cached GET against the GitHub commits API that has always been there, and a
repository-metadata read that names the current default branch. Each transfer is
capped at 1.5 seconds inside a 2.0 second whole-process bound, so worst-case
launch wall time is unchanged, and the cache still lives at
`~/.omh/runtime/update-check.json`. A network failure or timeout is a silent
skip that never blocks or delays the launch; a starved metadata read is recorded
as a partial and retried next interval rather than being read as a branch
change. An install that predates a recorded comparable identity reports the
check as inconclusive rather than guessing, and resolves the next time
update-check records one. A `stable` or
`local` channel install reports inconclusive too, but permanently -- only the
`preview` channel's `main` source ref ever records a comparable identity, so
the notice for that case says the comparison does not apply to that channel
instead of suggesting an `omh update` that cannot resolve it.

#### When upstream history is rewritten

Comparing two commit hashes only tells you they differ. It does not tell you
whether the branch moved forward, got rolled back, was force-pushed over, or
stopped existing under that name. The check used to treat every difference as
"you are behind"; after a rewrite that produced a confident, wrong answer, and a
recorded position that quietly pointed at a commit nobody could reach any more.

The watch now classifies the relationship before it claims anything. When the
recorded commit and the branch head differ, one bounded compare read decides
which of these it is:

| Ancestry | What it means | What you see |
| --- | --- | --- |
| `fast_forward` | The branch moved forward over your recorded commit | The normal `OMH update available: <old> -> <new>` notice; the only class `auto` acts on |
| `rewound` | The branch head is behind your recorded commit | Inconclusive, plus a recorded coverage gap |
| `rewritten` | The two histories diverged, so a force-push replaced commits | Inconclusive, plus a gap: `origin/main history rewritten (ancestry: rewritten)` |
| `cursor_unreachable` | The recorded commit is no longer reachable at all | Inconclusive, plus a gap |
| `branch_recreated` | Unreachable commit and a head that went backwards in time. Labeled a heuristic, because one read cannot prove recreation | Inconclusive, plus a gap |
| `default_branch_changed` | The repository's default branch is no longer the one being watched | The recorded position stays pinned; the notice names the old and new branch and points at `omh update-check status` |
| `unknown` | The probe failed, or the remote answered without enough to decide (shallow or delayed visibility) | `origin/main ancestry could not be verified`, plus an open gap. Never `up_to_date` |

Only a verified `fast_forward` may report `behind` or trigger `auto`. Everything
else is reported as inconclusive with a **coverage gap**: a record of the
interval the check can no longer speak for, naming the old and new refs and when
the uncertainty started. Silence never means complete coverage. An open gap is
printed ahead of the outcome, so it shows up even on a launch that would
otherwise have said nothing.

Gaps close on their own only when the recorded position converges again *and*
every declared recovery source answered definitively for that window. A readable
new head across a rewrite is not enough. When the head is readable but coverage
is incomplete, the gap stays open on purpose.

The extra reads stay rare and stay bounded. A compare fires only when the head
has actually moved away from the recorded commit, the tag read only inside an
open recovery window, and each one gets the same 1.5 second transfer inside its
own 2.0 second process bound as the launch probe. In `off` mode none of it runs.
The cache also keeps a ledger of recovery attempts, capped at 20 entries and
deduplicated by event, so re-probing the same rewritten head updates the existing
entry instead of appending a new one forever.

Inspecting and accepting a gap is a maintainer surface, not something a normal
user has to learn:

```sh
omh update-check status          # adds Ancestry: and Coverage gap: lines
omh update-check status --json   # the full v2 cache under last_check
omh update-check accept-gap      # after reviewing the rewritten history
```

`accept-gap` records that a human looked at the rewrite and the uncertain
interval and is willing to move on. It never claims the unreachable commits were
recovered, and it is idempotent: with no open gap it prints `No open coverage gap
to accept.` and changes nothing.

Compatibility: the cache grows to `omh_update_check_cache/v2` additively. An
older v1 cache reads as unknown ancestry with no gap, and the first v2 write
preserves every key it already had. A cache with no recorded default branch is
read as watching the branch it already watched, so upgrading never invents a
`default_branch_changed`. `off` remains the shipped default and still makes zero
network calls.

One boundary, stated plainly: what the watch delivers is the classification, the
notice, and the recorded gap. Before a later `omh update` records a new release
source commit, the update command enforces the engine's cursor-advance policy:
an open or unknown gap keeps the existing cursor pinned, while a verified
fast-forward or an explicitly accepted gap re-arms the write. `auto` acts on
nothing but a verified fast-forward, and a rewrite is always reported instead
of being absorbed.

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

Every skill OMH installs adds one index line to every Hermes request -- its
name and the first 57 characters of its description -- whether or not that
workflow is used. Its body costs about 8k characters each time the model loads
it, and a loaded body stays in the session's history until compaction. A `core`
install keeps that context weight bounded to the essentials; a `full` install
trades that weight for having every workflow's guidance available immediately,
with no `full` -> `core` skill left unpresented. Choose `full`
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
the context-cost report, which measures the `SKILL.md` bodies (loaded per skill
view) for both profiles and shows how much of it is text repeated verbatim across skills
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
skill-body total because they load only when a skill points a reader at them.

A `core` install still passes `omh doctor` because the core profile installs
a superset of the doctor health-floor skills.

### Reconciling An Existing Full Install Back To Core

`omh setup`, `omh install`, and `omh update` are non-destructive: they never
delete an installed skill directory, so reinstalling with the default `core`
profile after a `--full` install leaves every full-only skill on disk. The
recorded profile then says `core` while the effective context weight -- index
lines on every request, bodies on every load -- is still that of a `full`
install.

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
| Person using Hermes | Ask Hermes to set up your models. | Walks through the `main` model alias and the per-category model chains, provider connection, and session model switching. |
| Person using Hermes | Ask Hermes to make web search cheaper. | Walks through a provider API key and the web search and extract backend or free-tier choice as two separate reviewed diffs. |
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
`omx-runtime`, `pi-family-runtime`, and `omc-runtime`. This flag exists for
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
| `coding-runtime-team` | Hermes should prepare Hermes, OMX, pi-family, and OMC runtime handoffs with runtime templates and observed ladder status. |

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

From the primary Hermes home this unregisters managed skill directories,
reverses recorded config changes, and removes manifest-owned plugin, team and
legacy display artifacts from that home and its bot profiles. A named-profile
invocation targets only that profile. Store deletion is conditional on the
persisted reference inventory described below, not on the spelling of the command.

`omh uninstall` leaves Agent Skills trees (`.agents/skills/`,
`.claude/skills/`) in place; [Agent Skills removal](AGENT-SKILLS.md#removal)
covers them.

Command cleanup recognizes both the installer-owned legacy venv and real
`generations` venvs, including their `current` pointer and managed launcher.
A named-profile uninstall retains the shared command. `--keep-command` preserves
command files in every scope. Foreign commands, unrelated venvs, package-manager
roots, unrelated stores and user files are not attributed by layout names alone.

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

### What a full uninstall takes back out of `config.yaml`

`omh setup` writes `skills.external_dirs`,
`auxiliary.compression.fallback_chain`, `plugins.enabled`, `memory.provider`
and, when unset, `plugins.entries.omh.settings.omh_home` for both the implicit
default and a custom store binding.
Earlier versions also wrote `display.interface`, `display.skin` and
`display.sections`. A full uninstall reverses them, in the primary home and in
every bot profile when invoked from the primary home, or only the targeted
profile for a named-profile invocation.

It reverses a key only while the value there is still the one OMH wrote.
Setup records that at write time, per config path, in
`$OMH_HOME/runtime/state.json`. Change `memory.provider` to another product
afterwards and uninstall keeps your value and names the key it left alone.
A display value that consent let an earlier version migrate you off
(`display.interface`, `display.skin`) is put back rather than removed. Once
`omh setup` or `omh update` has released the display keys
([Returning `hermes` to stock Hermes](#returning-hermes-to-stock-hermes)),
uninstall reads every display value as yours and leaves it.

An install made before OMH kept that record, and not yet migrated, gets the
honest subset.
`display.skin: omh`, `plugins.enabled` containing `omh` and
`memory.provider: omh` name OMH by construction and are reversed anyway.
`display.interface: tui`, the `display.sections` children and the compression
fallback chain are values you could equally have chosen yourself, so they are
left in place and the uninstall output says which and why.

`--registration-only` reverses none of this; it removes the registration, and
the section the registration was the only occupant of, and nothing else,
because that scope exists to leave a working install unregistered. A `skills:`
the write record says you already had is left with you even when OMH's entry
was the last thing in it. `--dry-run` lists every key it would reverse and writes nothing.
A `config.yaml` that reversal empties is left in place: OMH does not delete a
file in your Hermes home.
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

For complete removal, preview `omh uninstall --all --dry-run --json` from the
primary home, inspect retained stores and failures, then run `omh uninstall --all`.
Remove the package-manager command only after confirming other homes no longer
need it; `--all` is not a bypass for shared-store or unreadable-inventory guards.

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
