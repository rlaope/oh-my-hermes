# omher Boundary

What omher (the desktop app under `apps/omher/`) may send, write, and import. This page is the full
statement of the boundary. `tests/test_omher_boundary.py` pins these sentences against the code, so a
behaviour change moves the code, this page and its test together. Glossary terms (omher, Elsewhere) are in `CONTEXT.md`; how the app is built
is in `apps/omher/README.md`.

## Rules

1. omher never patches Hermes. It reads Hermes' source-defined protocol and calls it as a client.
2. omher never writes to Slack, Discord or any other elsewhere session. It lists them and links to each thread in its own app, and nothing else.
   omher may pass a thread reference to the bot; the bot posts with its own tools and approvals.
3. omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`, and in folder chats the bridge created itself for an oh-my-hermes session (`folder.open`); the bridge has exactly one `prompt.submit` call site and it takes the main chat's id or such a folder chat's. Files the person attaches go to that same chat only, as bytes through Hermes' own `image.attach_bytes`, `pdf.attach` and `file.attach` (`chat.attach`, up to 100 MB each); the bridge never opens the person's files.
4. omher talks only to the person's own Hermes gateway on this machine, over loopback, through Hermes' own `connect_gateway`.
5. omher makes no LLM or API call itself. Every model call is Hermes'.
6. The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token the app made at launch.
7. The app starts the bridge as a child process and stops it when the app exits.
8. The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.
9. omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture (`assets/avatar.*`, through Hermes' `profiles.set_asset` when the gateway runs); the profile id, folder, config and sessions never change.
10. The only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`, plus `version` and one fixed `config --list`) with optional locks off, in folders the bot's own terminal runs used; omher never commits, checks out, pushes or edits a repository. Each read also turns off the programs a repository's own config can name (`core.fsmonitor`, filter drivers, diff textconv and external drivers, the in-tree `.gitattributes`), so git runs nothing else.
11. omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a fixed allow-list: `claude`, `codex`, `omh`, `pi`, `omp`, `grok`, with no arguments, in a pseudo-terminal in the folder the person picked. A chat session starts the same program with its fixed structured-mode arguments from the allow-list (`claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --permission-prompt-tool stdio`, `codex app-server`, `pi --mode rpc`, `omp --mode rpc`) on pipes; the only other argument is `--resume` with a Claude Code session id the shell checks is a UUID. The UI sends an agent id, never a command line or arguments; the shell refuses any other id. The process is stopped when its session is closed and when the app exits. What the agent then does in that folder is the agent's own, as if the person had typed its name in a terminal; its tool approvals come back as approval cards the person answers.
12. omher runs one installer, and only when the person presses Install on the first-run screen that appears because Hermes is missing: OMH's own one-line installer with `omher@beta` and `OMH_WITH_DESKTOP=0`, which installs Hermes with its official installer and then oh-my-hermes. On macOS it runs `f=$(mktemp) && trap 'rm -f "$f"' EXIT && curl -fsSL -o "$f" https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh && sh "$f" omher@beta`; on Windows, `$ErrorActionPreference = 'Stop'; try { & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta } catch { $_.Exception.Message; exit 1 }; exit $LASTEXITCODE`. Both are the documented one-liner, downloaded before it runs (or ending with its exit status), so a failed download or a failed install never reads as success. The command is fixed in the shell; nothing from the page reaches it.
13. omher shows a file from disk only when the bot named it in a `MEDIA:` line of its own answer, in its main chat or an elsewhere session (`media.read`, read-only, files over 25 MB are not read); the desktop app opens only a file the bridge just served this way.
14. omher reads OMH dag run records (`<omh home>/runtime/dag/*/*.json`) and their handoff files only for runs whose session is in the bot's own `state.db`, refuses symlinked handoffs and paths outside the dag folder, and never settles, retries or cancels a run; the Runs tab is read-only.
15. For the Runs graph omher also reads, never writes, Hermes' delegate_task folders (`<profile>/cache/delegation/live/deleg_*/`, the manifest and each task log's first and last lines), OMH's route records (`<omh home>/routing/route-provenance.json`) and a dag run's own `fanout-*-units.json`, and uses only the records written by the bot's own sessions.
16. For the Runs tab omher also reads, never writes, the CLI agents' own session files on this machine: Claude Code transcripts (`<claude config>/projects/*/*.jsonl` and each session's `subagents/agent-*` files) and Codex rollouts (`<codex home>/sessions/YYYY/MM/DD/rollout-*.jsonl`, plus `session_index.jsonl` for thread names). It keeps only a session's short title and each sub-run's name, model, state, times and final text (600 characters at most), never a prompt or a message body, skips symlinked folders and files, and never starts, resumes or stops a CLI session.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. A SESSIONS terminal is the person's own terminal hosted in a window: omher does not type into it,
read its output for any purpose but drawing it, or keep it after the app quits. A SESSIONS chat sends the agent
only what the person typed or answered, and reads its output only to draw the chat. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
