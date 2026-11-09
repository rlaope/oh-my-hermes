# omher Boundary

What omher (the desktop app under `apps/omher/`) may send, write, and import. This page is the full
statement of the boundary. `tests/test_omher_boundary.py` pins these sentences against the code, so a
behaviour change moves the code, this page and its test together. Glossary terms (omher, Elsewhere) are in `CONTEXT.md`; how the app is built
is in `apps/omher/README.md`.

## Rules

1. omher never patches Hermes. It reads Hermes' source-defined protocol and calls it as a client.
2. omher never writes to Slack, Discord or any other elsewhere session. It lists them and links to each thread in its own app, and nothing else.
3. omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`; the bridge has exactly one `prompt.submit` call site and it takes the main chat's id.
4. omher talks only to the person's own Hermes gateway on this machine, over loopback, through Hermes' own `connect_gateway`.
5. omher makes no LLM or API call itself. Every model call is Hermes'.
6. The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token the app made at launch.
7. The app starts the bridge as a child process and stops it when the app exits.
8. The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.
9. omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture (`assets/avatar.*`, through Hermes' `profiles.set_asset` when the gateway runs); the profile id, folder, config and sessions never change.
10. The only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`) with optional locks off, in folders the bot's own terminal runs used; omher never commits, checks out, pushes or edits a repository.
11. Outside Hermes, omher reads only the usage records coding CLIs write about themselves (the newest `rate_limits` event in `~/.codex/sessions`, `rate_limit_info` in `~/.claude/projects`), from the end of their newest session files; it never reads their auth files or tokens, writes nothing there and sends nothing anywhere.
12. Accounts (Settings › Accounts) are the one exception to rules 4, 10 and 11. They list the coding CLIs on this computer and their logins: the CLI's own home first, then the accounts added in omher, one folder each under `~/.omher/accounts/<cli>/<id>/` that a new session uses as the CLI's home. Besides the usage records of rule 11, omher reads only Claude Code's signed-in email (`.claude.json` `oauthAccount.emailAddress`), whether a CLI's login file exists (a stat, never opened), and the two fields `auth_mode` and `last_refresh` of Codex's `auth.json` when Codex has no status command; a local CLIProxyAPI is only counted by its auth file names. The app runs only the CLIs' own status and sign-in commands, as fixed argv (`claude auth status --json`, `claude auth login`, `codex --help`, `codex login status`, `codex login`) with the account's home set, and keeps from a status only signed in, email, plan and login method. The browser sign-in happens inside the CLI: omher never asks for, accepts, reads, copies or shows a token or key. It writes only under `~/.omher/accounts/` (one folder per account, `active.json`, `labels.json`) and deletes only `~/.omher/accounts/<cli>/<id>/`. An account switch never stops a running session.
13. omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a fixed allow-list: `claude`, `codex`, `omh`, `pi`, `omp`, `grok`, with no arguments, in a pseudo-terminal in the folder the person picked. The UI sends an agent id, never a command line or arguments; the shell refuses any other id. The process is stopped when its session is closed and when the app exits. What the agent then does in that folder is the agent's own, as if the person had typed its name in a terminal.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. A SESSIONS terminal is the person's own terminal hosted in a window: omher does not type into it,
read its output for any purpose but drawing it, or keep it after the app quits. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
