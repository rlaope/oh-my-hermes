# Implementation Boundaries

The full text of every scoped exception to OMH's core rule: no LLM, API,
Discord, Slack, GitHub, or network calls inside core `omh` features unless the
user explicitly approves a scoped integration. `AGENTS.md` (Implementation
Boundaries) keeps the rule, the Hermes-native child boundary, and one pointer
line per exception; this page holds the rest, moved there verbatim.
`tests/test_handoff_safety_contract_enforcement.py` pins every exception
(INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`, INVARIANT 2's
`NETWORK_CLIENT_BRIDGES` and `HERMES_INTERPRETER_SCRIPTS`), so a change to one
moves the code, this page and that test together.

## Scoped exceptions

The Hermes-native child boundary (`omh coding hermes-child dispatch`, with its
paired-run and final-review front doors) is not repeated here: its one copy
stays in `AGENTS.md`, where `tests/test_paired_run_arm_home.py` reads it.

- **Fanout dispatch bridge** (`omh coding fanout dispatch`, plus its
  `omh coding run` entry that builds and dispatches a one-unit contract
  through the same engine): an explicit operator command that spawns LOCAL
  agent CLIs (they make their own network calls; omh makes none) in per-unit
  worktrees against a frozen `fanout_contract/v2`, recording every spawn and
  exit as observed journal evidence. It never runs by default, never merges
  branches, never persists raw prompts under `.omh`, and never executes
  outside an explicit `dispatch`/`run` invocation against an explicitly named
  owner. Chat-prepared handoffs stay prompt-only for prompt-only profiles.
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
  `/channels/{id}/messages`, nothing posted, edited or joined. Its Slack-only
  brief mode (the omher briefing, `"mode": "brief"`) also GETs
  `users.conversations`, `conversations.members`, `conversations.replies` and
  `users.info`, and reads its own job's Hermes run records. Hermes strips bot
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
  Read [`docs/OMH-TUI-BOUNDARY.md`](OMH-TUI-BOUNDARY.md) before touching
  `src/tui/`.
- **Auto-resume shell hook** (scoped opt-in exception, the one place OMH
  writes outside its own and Hermes' homes): `omh auto-resume shell install
  [--shell zsh|bash|powershell]`, or a Yes to `omh setup`'s question (default
  No, asked only on a terminal while the shell's rc exists without the block),
  appends one block between `# >>> omh auto-resume >>>` and `# <<< omh
  auto-resume <<<` to the end of `${ZDOTDIR:-$HOME}/.zshrc`, `~/.bashrc` or
  PowerShell's current-user profile. `src/tui/shell_hook.py` is its only
  writer, and nothing in OMH runs a shell.
  - The write goes through a temporary file and a rename and keeps the file's
    mode; a symlinked rc is written at its target only inside the home. zsh
    and bash blocks are LF even in a CRLF rc, whose own bytes are kept. `omh
    auto-resume shell remove` deletes exactly that block and restores the file
    byte for byte.
  - The block starts no process unless `<omh_home>/tui/resume-pending` exists,
    a pid listed in `<omh_home>/tui/live-pids` (`b:<boot> <pid> ...`; a line
    from an older OMH without the `b:` word holds pids only and is read as
    such) no longer runs, or, on Linux, `/proc/sys/kernel/random/boot_id`
    differs from the recorded boot. It checks these with the shell's own
    builtins (`[[ -e ]]`, `read`, `kill -0`; PowerShell `Test-Path`,
    `Get-Content`, `Get-Process`). It runs only in interactive shells without
    `OMH_AUTO_RESUME_DONE`, `HERMES_SESSION_ID`, `OMH_TUI_SESSION_FILE` or
    `CI`, and runs `omh auto-resume shell-start` once at the first prompt (zsh
    `zle-line-init`, kept out of the history by a one-shot `zshaddhistory`
    hook; bash `PROMPT_COMMAND`; PowerShell console host). `shell-start`
    reopens only a session recorded under this terminal's key.
  - No third-party terminal's files are written; their pane ids are only read.
  - Separately, a bare `omh` reopens the session its terminal (else, outside
    omher, its folder) dropped, once, at once, as `omh --resume <id>` would. It
    is on by default and off with `omh --new`, `OMH_AUTO_RESUME=0` or `omh
    auto-resume set --mode off`, and runs no extra process. It claims only from
    a Hermes home this launch opens, decided read-only before the claim, and
    opens the session in the home it was recorded in. Full statement:
    [`docs/OMH-TUI-BOUNDARY.md`](OMH-TUI-BOUNDARY.md), "Coming back after a
    closed terminal".
- **omher** (apps/omher/, the Tauri desktop app for macOS, Windows and Linux) is not part of core omh and nothing in src/ imports it. "omher" names the app only; "OMH" and "oh-my-hermes" name the harness. It shows Hermes bots, one main chat each, and the bot's other sessions read-only; it sends only to a bot's main chat and to folder chats its bridge opened itself, reaches only the person's own loopback gateway through a local bridge, and makes no model or API call itself. Its SESSIONS start only allow-listed local agent CLIs, when the person asks. Every widening is a numbered rule in [docs/OMHER-BOUNDARY.md](OMHER-BOUNDARY.md), pinned by `tests/test_omher_boundary.py`; read it before touching the app.

## Short form

The one-line form of the same exceptions, formerly under What This Repo Is in
`CLAUDE.md`:

- `omh coding fanout dispatch` (and its `omh coding run` entry): explicit
  opt-in; spawns local agent CLIs, which make their own network calls. Nothing
  runs without that command.
- `omh_jev_ask`: POSTs typed questions to Jev with the user's own key, only
  when the user named Jev in that turn and a key resolves (TypeSafe, at the
  HTTPS `TYPESAFE_BASE_URL` API root when set, or OpenRouter only
  with the operator setting in `<omh_home>/jev/settings.json`).
  Stdlib, HTTPS only, redirects refused; the same file's
  `local_http_endpoint` opt-in alone allows plain HTTP, and only to a
  loopback, private, or link-local `TYPESAFE_BASE_URL`.
  `src/plugin_bundle/omh/jev_ask_client.py` is an in-process
  network client in `src/`, pinned by INVARIANT 2's
  `NETWORK_CLIENT_BRIDGES`. Third-party Jev plugins are never called.
- The OMH TUI's update notice: GETs npm's latest `oh-my-hermes` version, at
  most once a day per OMH home, on a background thread, and names a newer one
  on the info line. Stdlib, HTTPS only, one fixed host (`registry.npmjs.org`),
  redirects off it refused, only the version string kept, nothing about the
  person sent. Off with `OMH_TUI_UPDATE_CHECK=0`, `omh theme update-check
  off`, or an explicit `omh update-check` `off` (a stored mode, not the
  default). `src/tui/update_notice.py` is another client in
  `NETWORK_CLIENT_BRIDGES`. Only `src/tui/app.py` and `src/commands/setup.py`
  may import it; the latter reads `latest` once in an explicit `omh update` on
  an installer-managed stable install to pick the release wheel to download.
- Local proofreader (scoped exception, owner-approved 2026-11-18, automatic
  checks opt-in): inline marks in main/clarify free-text fields, on Alt+P or,
  only with `OMH_PROOFREAD=1` (off by default), after 600 ms quiet, with explicit
  Alt+P correction only at the cursor, to a loopback-only local LanguageTool
  server using stdlib `http.client` and `socket`. No proxies or redirects;
  five-second elapsed deadline, 512 KiB reply cap, 20,000-character draft cap.
  Masked fields send nothing; code, commands, image tokens and paste chips are
  excluded. No automatic server installation/startup or silent rewrite/submit.
  Accept/skip is explicit per issue; accepted edits use `Composer.replace`
  with normal undo. Only `tui/app.py` may import `tui/proofread.py`, pinned by
  `NoNetworkClientInSource.test_local_proofreader_import_surface_and_owner`.
- The `show-reel` toolkit scripts `toolkit/scripts/eleven.py`, `narrate.py`
  (ElevenLabs, by spawning `curl` with the key on stdin) and
  `codex_ref_image.sh` (the user's codex CLI): package data the user runs with
  their own `ELEVENLABS_API_KEY` or codex login. OMH never imports or runs
  them; without the credential they exit 2. `eleven.py` is in INVARIANT 1's
  `PROCESS_SPAWN_ALLOWLIST`.
- The OMH TUI's gateway child, `src/tui/attach/gateway_attach.py`: not core.
  It runs only on Hermes' interpreter, spawned by path, imported by nothing in
  `src/`, and reaches the person's own gateway over loopback as Hermes' Ink TUI
  does. INVARIANT 2's `HERMES_INTERPRETER_SCRIPTS` holds it to a closed allow
  list of imports, names and name flows measured from the script. It is not a
  sandbox: an allowed Hermes function called with other arguments, and where
  the grant's url points, are beyond it.
- The auto-resume shell hook: opt-in only (`omh auto-resume shell install` or a
  Yes in `omh setup`, default No). One marked block at the end of the zsh, bash
  or PowerShell rc, written only by `src/tui/shell_hook.py` and removed byte
  for byte by `omh auto-resume shell remove`. It starts no process unless a
  dropped OMH session waits, then runs `omh auto-resume shell-start` once at the
  first prompt. A bare `omh` reopening a dropped session needs no hook.
- omher, the desktop app under `apps/omher/`: not core. ("omher" is the app;
  "OMH"/"oh-my-hermes" is the harness.) Its Python bridge reaches only the
  person's own gateway over loopback, sends only to a bot's main chat and the
  folder chats it opened, and makes no model or API call; nothing in `src/`
  imports it. `docs/OMHER-BOUNDARY.md` states it and
  `tests/test_omher_boundary.py` pins it.

## Maintenance procedure files

- `REVIEW.md` defines a blocking finding in this repository. Nothing loads it
  automatically; a reviewer reads it.
- `.github/labels.yml` is the label manifest and the path globs that map a
  changed file to an `area/` label. It is the entire allowlist; never apply or
  create a label outside it.
- `.claude/skills/triage-sweep/`, `.claude/skills/review-sweep/` and
  `.claude/skills/model-onboarding/` only make these reachable as Claude Code
  slash commands. They defer to the files above, which stay the single source
  of truth.
