# OMH Agent Contract

The operating contract for every coding agent working on oh-my-hermes: Codex,
Claude Code, Hermes runtime/handoff paths, and generic executor profiles.
`CLAUDE.md` is the engineering manual for all of them, not only Claude Code
(commands, gates, the generated-artifact map, known pitfalls); read it before
running gates or editing generated output. `CONTEXT.md` is the glossary.

## Product Direction

Read `docs/DIRECTION.md` before changing architecture, workflow behavior,
wrapper contracts, generated skill guidance, or coding delegation semantics.

OMH is a Hermes-native wrapper orchestration layer. Hermes owns chat intake,
clarification, source-backed research, planning, and status narration. Main
coding work goes to the selected coding owner through explicit prepared
handoffs and observed evidence.

Codex, Claude Code, and Hermes runtime/handoff paths are all first-class
product surfaces. A user may pick one coding owner for a task, but feature
design, contracts, docs, setup, memory recall, and status/reporting consider
all three unless a change is explicitly scoped to one executor. Name the
selected owner (`codex`, `claude-code`, `hermes`, a runtime profile, or a
generic executor); use Codex-specific wording only for Codex-only lifecycle
features. Where support differs, document the difference as a capability
boundary.

Do not turn OMH into a hidden Hermes runtime patch, transport bot, network
service, LLM router, or secret coding executor. Every sanctioned exception is
explicit and opt-in, never hidden and never a default, and is listed under
Implementation Boundaries.

## Command Audience

Natural-language Hermes chat is the normal product surface. Most people should
only need `omh setup`, `omh update`, and `omh doctor`; removal and repair
commands are exceptional maintenance paths, not the day-to-day OMH workflow.

`omh chat`, `omh coding`, `omh runtime`, `omh memory`, `omh loop`, `omh goal`,
`omh harness`, `omh capabilities`, `omh release`, `omh state`, and similar
control-plane groups exist for Hermes Agent, wrappers, coding agents,
automations, and maintainers. Public docs may show them as integration or
operator references, labeled with their audience, never as something a normal
user must memorize. Describe the human action as an intent or outcome (asking
Hermes to prepare coding work) and keep the backend command in the
agent-facing reference.

## Delivery Grain

One user goal should normally produce one PR.

Plan, explain, and report at the full user-goal grain. Do not frame a
recommendation as "the first PR", "initial PR", "first slice", or a similar
partial unit unless the user asks for phased delivery or an independent
release/rollback boundary forces a split. When a split is forced, state the
complete target capability first, then the split reason and the remaining gap.

Planning docs, tests, implementation, code-review fixes, CI fixes, and small
follow-up docs for the same goal belong in the same PR, as focused commits.
Do not split review feedback or small follow-up fixes into new PRs merely
because a previous commit exists. Split only when the next change is a
different user-facing goal, has independent release or rollback value, would
make the current PR too risky to review, is blocked by an external decision,
or the user asks for separate PRs.

When the user asks to merge, finish review fixes in the current PR first,
rerun verification, wait for required checks, then merge if authority is
clear.

## Pull Request Reports

PR descriptions must read like a useful feature report, not a terse changelog.
Use the repository PR template and fill every relevant section with concrete,
reviewable detail:

- What capability, workflow, command, or contract changed.
- Why the change exists: the user problem, product gap, or operational failure
  behind it.
- What the user or operator can do after the change that they could not do
  before.
- How it works at the boundary level: modules, commands, generated files,
  persisted state, or wrapper contracts touched.
- What verification was actually observed: CI, targeted tests,
  generated-output checks, dry-runs, or manual Hermes/TUI gaps.
- What risks, rollout notes, compatibility concerns, or follow-ups remain.

Prefer a short narrative plus bullets that make the feature's origin, behavior,
and evidence obvious to a reviewer reading the PR without the chat history.

## Implementation Boundaries

- No LLM, API, Discord, Slack, GitHub, or network calls inside core `omh`
  features unless the user explicitly approves a scoped integration. The
  approved ones follow.
- **Fanout dispatch bridge** (`omh coding fanout dispatch`, plus its
  `omh coding run` entry that builds and dispatches a one-unit contract
  through the same engine): an explicit operator command that spawns LOCAL
  agent CLIs (they make their own network calls; omh makes none) in per-unit
  worktrees against a frozen `fanout_contract/v2`, recording every spawn and
  exit as observed journal evidence. It never runs by default, never merges
  branches, never persists raw prompts under `.omh`, and never executes
  outside an explicit `dispatch`/`run` invocation against an explicitly named
  owner. Chat-prepared handoffs stay prompt-only for prompt-only profiles.
- **Hermes-native child boundary** (`omh coding hermes-child dispatch`): one
  isolated local Hermes single-query process (`hermes chat --query-file -`,
  the Hermes transport that reads a prompt from stdin). It requires
  `--confirm-dispatch`, takes prompts only through stdin/files, enforces a
  depth-one recursion limit (OMH dispatch depth; inside a paired-run arm,
  Hermes' own one-level `delegate_task` children are allowed when the run's
  `--arm-toolsets` names `delegation`), runs safe-mode file tools by default, records
  authenticated `routing_observation/v1` evidence, and never runs
  automatically. Two front doors reuse it without adding a process authority:
  - `omh coding paired-run dispatch` for confirmed evaluation cells: one
    digest-matching task file per frozen task, task bytes over child stdin,
    detached per-cell worktrees under an atomically unique invocation-owned
    parent, signed evaluation bindings, removal of only the paths that
    invocation reserved, and no persisted task body. Both arms run
    `--toolsets file,skills`; only the explicit `--arm-toolsets` opt-in may
    add `terminal` and `delegation`, to both arms identically, signed into
    each cell and checked at fan-in, with Hermes' command approval left on;
    with `delegation` both arm homes pin the same child cap and the arm's
    model for every child, and fan-in refuses a cell whose child sessions ran
    another model. Executors without a
    receipt-capable adapter are refused without substitution;
    caller-injected adapters stay the executor-neutral seam. It is the one
    caller that leaves safe mode: each arm runs a declared, receipt-signed
    arm setup in its own disposable Hermes home (the variant with the OMH
    plugin, a disposable OMH home and its frozen `exposed_skills`, the
    baseline with neither; both the run's declared toolsets), served by a
    harness-owned `hermes gateway run` in its own process group that the
    invocation warms before timing and stops on exit, never a service
    manager. A custom provider is declared by base URL (https, or http to a
    loopback host), API mode and key variable name; its secret arrives only
    by environment. Fan-in refuses a cell whose signed setup contradicts its
    arm.
  - `omh coding fanout dispatch --final-review`, after dispatcher-observed
    integration GREEN: the explicit flag, a clean integrated tree, named
    Hermes provider/model settings; four read-only lenses in disposable,
    write-denied detached worktrees under fixed concurrency, parsing only a
    closed verdict token, unable to merge or mutate the integrated checkout.
- **Fanout diagnostics** (`omh coding fanout dispatch --diagnostics`): only
  the closed local diagnostic command set, after producer verification GREEN.
  Binaries come from `PATH`; no shell text or user-selected executable;
  detached fixed-revision worktrees; messages and absolute paths stripped;
  child environment redacted; concurrency, time and output capped; the
  provider's whole process tree always reaped and every temporary worktree
  removed. On Windows the provider starts suspended, enters a kill-on-close
  Job Object, and resumes only after ownership succeeds; clean evidence
  requires the Job Object to report zero active processes.
- **Local proofreader** (scoped exception, owner-approved 2026-11-18 as
  opt-in for automatic checks): the main or clarify free-text composer checks unprotected
  draft text on a local LanguageTool server on Alt+P, or after 600 ms quiet only
  when `OMH_PROOFREAD=1` opts in (off by default). Alt+P explicitly checks or
  opens only the issue at the cursor. Automatic results only underline; they never take keys or open review.
  `src/tui/proofread.py` uses stdlib `http.client` and `socket`, plain HTTP to
  loopback IP literals only (`localhost` is pinned to `127.0.0.1`), no proxies
  or redirects, a five-second elapsed deadline, a 512 KiB reply cap and a
  20,000-character draft cap. Masked fields send nothing; code, commands,
  image tokens and paste chips are excluded. No automatic server installation
  or startup, silent rewrite or submission. Replacement and local dictionary
  changes are explicit per issue; accepted edits use `Composer.replace` and its
  normal undo. Only `tui/app.py`
  may import the client, pinned by
  `NoNetworkClientInSource.test_local_proofreader_import_surface_and_owner` in
  `tests/test_handoff_safety_contract_enforcement.py`.
- **`omh_jev_ask`**, a scoped network integration: the plugin tool POSTs
  typed questions to Jev with the user's own key and returns probabilities.
  It runs only when the user's own message for that turn names Jev (a
  per-turn marker `pre_llm_call` records; otherwise it returns
  `consent_not_observed` and opens no socket), and only when a route
  resolves: `TYPESAFE_API_KEY`, with TypeSafe's optional `TYPESAFE_BASE_URL`
  API root for the TypeSafe endpoint, or `OPENROUTER_API_KEY` plus
  `{"openrouter_route": true}` in `<omh_home>/jev/settings.json`, which OMH
  never writes. Stdlib only, HTTPS only, two route identities, no redirects,
  bounded bodies, no retry after a sent request times out. The one plain-HTTP
  case is the same file's `{"local_http_endpoint": true}`, which lets
  `TYPESAFE_BASE_URL` name `localhost` or a loopback, private, or link-local
  IP literal (a self-hosted Jev-compatible server); its `typesafe_model` names
  the model such a non-TypeSafe endpoint serves. It
  persists no key, `state`, question text, or reply; one metadata-only ledger
  row per ask. `src/plugin_bundle/omh/jev_ask_client.py` is one of the scoped
  in-process network clients in `src/`, and only `tools/jev_ask_tool.py` may
  import it. Third-party Jev plugins are never called, and `omh doctor` reads
  no credential value.
- **The OMH TUI's update notice**, a scoped network integration: at
  most once a day per OMH home, on a background thread that never holds the
  start or the screen, the TUI GETs `https://registry.npmjs.org/oh-my-hermes/latest`
  and keeps only its `version`, cached with the time of the ask in
  `<omh_home>/tui/update-check.json`; a newer release than the running one is
  named beside the info line's badge. Stdlib only, HTTPS only, one fixed host,
  redirects off that host refused, a 3 s socket timeout, a bounded reply, and
  nothing about the person sent; every failure is silent and keeps what the
  cache knew. Off with `OMH_TUI_UPDATE_CHECK=0`, `omh theme update-check
  off`, or `omh update-check` stored as `off` (`update_check.mode` in
  `<omh_home>/setup-profile.json`, written by `omh update-check set` or
  confirmed in `omh setup`; a home that never stored a mode keeps it on), and
  nothing is asked without an OMH home. `src/tui/update_notice.py`
  is another in-process network client in `src/`. Only `tui/app.py` and
  `commands/setup.py` may import it; the latter calls `fetch_latest` once in
  an explicit `omh update` on an installer-managed stable install, to pick the
  release wheel it is about to download, and never moves on a failed read.
- **Show-reel provider scripts**: `src/skills/show_reel_toolkit/scripts/eleven.py`
  and `narrate.py` (ElevenLabs TTS/STT/SFX/music by spawning `curl`, key from
  `ELEVENLABS_API_KEY` only, passed on curl's stdin) and `codex_ref_image.sh`
  (the user's signed-in codex CLI) ship as inert package data. Only the user
  runs them, with their own credential; without it they exit 2 and send
  nothing. OMH core, install, update, routing and doctor never import or
  execute them; `eleven.py` is in INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`, and
  the companion-nonexecution tests cover both Python scripts.
- **Channel watch collector**: `src/skills/channel_watch_toolkit/scripts/channel_watch.py`
  ships as inert package data (owner-approved scoped integration, 2026-11-15).
  OMH core, install, update, routing and doctor never import or execute it;
  nothing in `src/` imports it, and it is in INVARIANT 2's
  `NETWORK_CLIENT_BRIDGES` with no importer. The person (or their bot, on their
  request) copies it into `<profile>/scripts/channel_watch_<watch>.py`, and a
  Hermes cron job runs it on Hermes' interpreter before the judging step. It is
  stdlib only and read-only: GETs to Slack `auth.test` and
  `conversations.history`, or Discord `/users/@me` and
  `/channels/{id}/messages`, nothing posted, edited or joined. Hermes strips bot
  tokens from a cron script's environment, so it reads exactly
  `SLACK_BOT_TOKEN` or `DISCORD_BOT_TOKEN` by key name: from the environment
  first, else that key from `$HERMES_HOME/.env`. It never prints or stores it
  (a token with a space or control character is refused without echoing it);
  without one it exits 2 and sends nothing.
  Redirects are refused, replies bounded, and `api_base` overrides are accepted
  only for loopback hosts (tests). Config, cursors, exit codes and the install
  command are in its `README.md`; `tests/test_channel_watch_toolkit.py` runs it
  against a fake API on 127.0.0.1.
- **The OMH TUI** (bare `omh`) is a foreground frontend over Hermes' own
  gateway, not an execution surface: it relays only what the person types,
  answers no request on their behalf, and makes no model call; the one switch
  it makes on its own is the session's model, at a turn boundary, when Hermes'
  configured default model moved (owner, 2026-10-25). The one prompt it sends
  that the person did not type is OMH's fixed onboarding prompt
  (`src/tui/onboarding.py`), once, in a new session, only under `omh --onboard
  model-setup`; the accepted last question of an interactive `omh setup` is
  its only automatic caller, and a person may run it themselves (owner,
  2026-11-18). Its gateway
  child, `src/tui/attach/gateway_attach.py`, runs on Hermes' interpreter under
  INVARIANT 2's `HERMES_INTERPRETER_SCRIPTS` allow list. Inside a herdr pane
  only, gated on the same pane environment (`HERDR_ENV=1`, `HERDR_PANE_ID`)
  as herdr's own Hermes plugin, it runs the person's own `herdr` CLI (an
  absolute `HERDR_BIN_PATH` or `herdr` on PATH) to report its
  idle/working/blocked state on each change and release the pane on exit
  (`src/tui/herdr.py`, in INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`): a local
  socket, no network call. The gateway child does not get the pane's
  `HERDR_PANE_ID`; herdr's CLI and skill still work there, without a
  current-pane default. On `/gateway restart`, typed by the person or offered
  once after an update, and confirmed in the slot, it runs Hermes' own `hermes
  gateway restart --yes --detach` on Hermes' interpreter
  (`src/tui/gateway_restart.py`, in INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`)
  and reattaches to the same session; it signals no process itself. `omh
  update` asks the same on a terminal, defaulting to no, or takes
  `--restart-gateway`, and then runs the person's `hermes` with those
  arguments. When `omh update` moved the generation under a running TUI and
  the person picks Restart between turns, the TUI exits and the `omh` that
  launched it starts the installed generation's `omh --resume <id>`.
  Read [`docs/OMH-TUI-BOUNDARY.md`](docs/OMH-TUI-BOUNDARY.md) before touching
  `src/tui/`.
- **omher** (apps/omher/, the Tauri desktop app for macOS, Windows and Linux) is not part of core omh and nothing in src/ imports it. "omher" names the app only; "OMH" and "oh-my-hermes" name the harness. It shows Hermes bots, one main chat each, and the bot's other sessions read-only; it sends only to a bot's main chat and to folder chats its bridge opened itself, reaches only the person's own loopback gateway through a local bridge, and makes no model or API call itself. Its SESSIONS start only allow-listed local agent CLIs, when the person asks. Every widening is a numbered rule in [docs/OMHER-BOUNDARY.md](docs/OMHER-BOUNDARY.md), pinned by `tests/test_omher_boundary.py`; read it before touching the app.
- No Hermes core patching.
- Runtime artifacts are local, deterministic, schema-versioned, and
  metadata-only by default.
- Preserve prepared versus observed boundaries. `prepared_not_observed` is not
  execution, review, CI, merge-readiness, or merge evidence.
- Wrapper sessions own chat continuity and plan decisions only. Linked runtime
  runs own handoff, dispatch, execution, verification, review, CI, and merge
  evidence.
- Project memory lives under `.omh/memory/` as reviewed OMH-local prepared
  context. Keep candidates separate from approved records, preserve
  review-first defaults, and never present recall packs as execution, review,
  CI, merge, or Hermes internal-memory evidence.
- Never hand-edit a generated file or marked region: edit its producer,
  regenerate, and commit producer and output together (the map is in
  `CLAUDE.md`, Generated Artifacts Map; every gate is byte-exact).

## Coding Style

- Code, docs, commit messages, PR text, and user-facing CLI output are
  English by default. Localized output (ko/ja/zh) is explicit opt-in through
  `--language` or `OMH_LANG`; never auto-detect the OS locale.
- OMH is an open-source product for every user on every terminal. Design a
  fix or a look for all of them. Never tune it to the maintainer's own
  machine, terminal, theme or language: the maintainer's setup is where a
  problem shows up and gets measured, not the target. A capability-detected
  enhancement may sit on top of a fix that works everywhere, but never
  replaces it.
- The OMH TUI and CLI frame is English for everyone: TUI labels, key hints,
  picker rows, TUI notices and CLI output. Never switch it by the language of
  the conversation or of text a model or a person wrote. That text keeps its
  own language; the frame around it does not follow. The only exception is
  the explicit `--language` / `OMH_LANG` opt-in above. Chat and messenger
  reply copy (`src/wrapper/localized_copy.py`) is a separate surface. It
  follows the person's message and is not covered by this rule.
- Reply to Korean user messages in polite Korean; no banmal or casual endings
  unless the user asks for that tone. Name what exists, what is missing, and
  the complete target behavior, rather than process labels or "small first
  PR" framing.
- Keep public claims conservative and test-backed.
- No new dependency unless the user approves it and its packaging story.
- A routing or policy change ships negative cases beside its positive ones
  and moves the reviewed count pins in the same commit (details in
  `CLAUDE.md`, Code Conventions).

## Verification

Use the smallest check that proves the claim, then broaden when the touched
surface is shared. Before claiming done, run the gates listed in `CLAUDE.md`
(Build & Test) and the full suite; for a docs or contract change those include
`uv run python -m omh.cli docs navigation --check` and
`uv run python -m omh.cli docs claims --check --json`.

For direction, docs, generated skill, wrapper contract, lifecycle, or runtime
artifact changes, add or update tests that lock the public contract.

CodeGraph (`docs/CODEGRAPH.md`) is a navigation aid before broad exploration;
its index under `.codegraph/` is machine-local, and only
`.codegraph/.gitignore` is committed. Its output is prepared context, never
execution, review, CI, merge-readiness, or merge evidence.

### Reporting Our Own Numbers

A rate OMH computes about itself is a claim, so it carries what it divided.
Every percentage in a payload uses the `omh_reported_rate/v1` shape
(`src/quality/reported_rate.py`, checked by `reported_rate_shape_errors()`):
the buckets its numerator summed, what its denominator counted, and every
observation class excluded before either count. Two traps:

- **An empty denominator is not 0%.** `max(1, count)` in a divisor turns an
  empty corpus into a confident zero. Report `percent: null` with basis
  `no_observations`, and let an unmeasured rate fail its target rather than
  pass it.
- **A composed numerator says so.** When a rate sums more than one outcome
  bucket, name them in the payload, not only in a text formatter; every
  non-human consumer reads the JSON.

The same rule governs prose: a headline number in a commit, PR, or report names
the arm, the corpus, the selection rule, and the committed artifact it came
from. A number without those is `prepared_not_observed`, not a result.

## Repository Maintenance Procedures

Three maintainer procedures are executor-neutral: any coding agent runs them
the same way. When asked to triage, label, review the backlog, or onboard a
model, read the matching file and follow it rather than improvising. Each
states its own allowlist, dry-run default, and boundaries; the two sweeps are
manual and default to a dry run, and none runs in CI.

| Procedure | File | What it does |
| --- | --- | --- |
| Triage sweep | `docs/TRIAGE-SWEEP.md` | Labels issues and PRs that have no `area/` label, deriving a PR's areas from its changed files against `.github/labels.yml` |
| Review sweep | `docs/REVIEW-SWEEP.md` | Reviews PRs carrying no review at their current head commit, against `REVIEW.md` |
| Model onboarding | `docs/MODEL-ONBOARDING.md` | Moves a new model generation or sibling through recognition, research, calibration, both routing lanes, pricing, machine placement, gates, and the measurement close |

- `REVIEW.md` defines a blocking finding in this repository. Nothing loads it
  automatically; a reviewer reads it.
- `.github/labels.yml` is the label manifest and the path globs that map a
  changed file to an `area/` label. It is the entire allowlist; never apply or
  create a label outside it.
- `.claude/skills/triage-sweep/`, `.claude/skills/review-sweep/` and
  `.claude/skills/model-onboarding/` only make these reachable as Claude Code
  slash commands. They defer to the files above, which stay the single source
  of truth.

## Git And Commits

Branch before the first edit, unless the current branch is already dedicated to
that exact user goal. Name the branch by the kind of change, never by the
executor: `feature/<topic>` for a new or extended capability, `fix/<topic>`
for a defect, `omh/<topic>` for everything else (docs, release, maintenance,
measurement). Existing branches keep their names.

Every commit carries DCO signoff and the Lore-style trailers:

```text
Constraint: <external constraint that shaped the decision>
Rejected: <alternative considered> | <reason>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <forward-looking warning>
Tested: <what was verified>
Not-tested: <known gaps>
Signed-off-by: <name> <email>
```

Never revert user changes or unrelated untracked files. If an unrelated file is
dirty, leave it alone and report it.
