# omher Boundary

What omher (the desktop app under `apps/omher/`) may send, write, and import. This page is the full
statement of the boundary. `tests/test_omher_boundary.py` pins these sentences against the code, so a
behaviour change moves the code, this page and its test together. Glossary terms (omher, Elsewhere) are in `CONTEXT.md`; how the app is built
is in `apps/omher/README.md`.

## Rules

1. omher never patches Hermes. It reads Hermes' source-defined protocol and calls it as a client.
2. omher never writes to Slack, Discord or any other elsewhere session. It lists them and links to each thread in its own app, and nothing else.
   omher may pass a thread reference to the bot; the bot posts with its own tools and approvals.
3. omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`; the bridge has exactly one `prompt.submit` call site and it takes the main chat's id.
4. omher talks only to the person's own Hermes gateway on this machine, over loopback, through Hermes' own `connect_gateway`.
5. omher makes no LLM or API call itself. Every model call is Hermes'.
6. The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token the app made at launch.
7. The app starts the bridge as a child process and stops it when the app exits.
8. The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.
9. omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture (`assets/avatar.*`, through Hermes' `profiles.set_asset` when the gateway runs); the profile id, folder, config and sessions never change.
10. The only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`, plus `version` and one fixed `config --list`) with optional locks off, in folders the bot's own terminal runs used; omher never commits, checks out, pushes or edits a repository. Each read also turns off the programs a repository's own config can name (`core.fsmonitor`, filter drivers, diff textconv and external drivers, the in-tree `.gitattributes`), so git runs nothing else.
11. omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a fixed allow-list: `claude`, `codex`, `omh`, `pi`, `omp`, `grok`, with no arguments, in a pseudo-terminal in the folder the person picked. The UI sends an agent id, never a command line or arguments; the shell refuses any other id. The process is stopped when its session is closed and when the app exits. What the agent then does in that folder is the agent's own, as if the person had typed its name in a terminal.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. A SESSIONS terminal is the person's own terminal hosted in a window: omher does not type into it,
read its output for any purpose but drawing it, or keep it after the app quits. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
