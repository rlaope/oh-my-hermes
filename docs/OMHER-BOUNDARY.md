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
12. Accounts (Settings › Accounts) are the one exception to rules 4, 5 and 11. From CLIProxyAPI's auth files omher keeps only `email`, `disabled`, `expired`, `last_refresh` and `type`, and drops every other field, tokens included, right after parsing; from an omher account folder it reads only Claude Code's signed-in email and the usage records of rule 11. It writes only under `~/.omher/accounts/` (one folder per account and `active.json`) and deletes only `~/.omher/accounts/<cli>/<id>/`. The bridge only checks that CLIProxyAPI's loopback port answers and sends nothing; the app sends one kind of request, enabling, disabling or removing one CLIProxyAPI auth file, to 127.0.0.1 only, with a management key kept in the OS keychain and never in a file. omher never reads, copies or shows a token, and an account switch never stops a running session.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
