# omher Boundary

What omher (the desktop app under `apps/omher/`) may send, write, and import. This page is the full
statement of the boundary. `tests/test_omher_boundary.py` pins these sentences against the code, so a
behaviour change moves the code, this page and its test together. Glossary terms (omher, Elsewhere) are in `CONTEXT.md`; how the app is built
is in `apps/omher/README.md`.

## Rules

1. omher never patches Hermes. It reads Hermes' source-defined protocol and calls it as a client.
2. omher never writes to Slack, Discord or any other elsewhere session. It lists them and links to each thread in its own app, and nothing else.
   omher may pass a thread reference to the bot; the bot posts with its own tools and approvals.
3. omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`, and in folder chats the bridge created itself for an oh-my-hermes session (`folder.open`); the bridge has exactly one `prompt.submit` call site and it takes the main chat's id or such a folder chat's.
4. omher talks only to the person's own Hermes gateway on this machine, over loopback, through Hermes' own `connect_gateway`.
5. omher makes no LLM or API call itself. Every model call is Hermes'.
6. The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token the app made at launch.
7. The app starts the bridge as a child process and stops it when the app exits.
8. The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.
9. omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture (`assets/avatar.*`, through Hermes' `profiles.set_asset` when the gateway runs); the profile id, folder, config and sessions never change.
10. The only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`, plus `version` and one fixed `config --list`) with optional locks off, in folders the bot's own terminal runs used; omher never commits, checks out, pushes or edits a repository. Each read also turns off the programs a repository's own config can name (`core.fsmonitor`, filter drivers, diff textconv and external drivers, the in-tree `.gitattributes`), so git runs nothing else.
11. omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a fixed allow-list: `claude`, `codex`, `omh`, `pi`, `omp`, `grok`, with no arguments, in a pseudo-terminal in the folder the person picked. A chat session starts the same program with its fixed structured-mode arguments from the allow-list (`claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --permission-prompt-tool stdio`, `codex app-server`, `pi --mode rpc`, `omp --mode rpc`) on pipes; the only other argument is `--resume` with a Claude Code session id the shell checks is a UUID. The UI sends an agent id, never a command line or arguments; the shell refuses any other id. The process is stopped when its session is closed and when the app exits. What the agent then does in that folder is the agent's own, as if the person had typed its name in a terminal; its tool approvals come back as approval cards the person answers.
12. omher runs one installer, and only when the person presses Install on the first-run screen that appears because Hermes is missing: OMH's own one-line installer with `omher@beta` and `OMH_WITH_DESKTOP=0`, which installs Hermes with its official installer and then oh-my-hermes. On macOS it runs `f=$(mktemp) && trap 'rm -f "$f"' EXIT && curl -fsSL -o "$f" https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh && sh "$f" omher@beta`; on Windows, `$ErrorActionPreference = 'Stop'; try { & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta } catch { $_.Exception.Message; exit 1 }; exit $LASTEXITCODE`. Both are the documented one-liner, downloaded before it runs (or ending with its exit status), so a failed download or a failed install never reads as success. The command is fixed in the shell; nothing from the page reaches it.
13. omher updates itself only through Tauri's updater, and only from one fixed address: `https://github.com/rlaope/oh-my-hermes/releases/download/omher-latest/latest.json`, which the release workflow rewrites on every `omher-v*` release. It installs a build only when its signature matches the public key pinned in `tauri.conf.json`, and only after the person presses the update button; then it restarts omher. This is omher's one network request of its own; it sends nothing about the person or their bots.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. A SESSIONS terminal is the person's own terminal hosted in a window: omher does not type into it,
read its output for any purpose but drawing it, or keep it after the app quits. A SESSIONS chat sends the agent
only what the person typed or answered, and reads its output only to draw the chat. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
