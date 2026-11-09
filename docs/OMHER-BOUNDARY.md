# omher Boundary

What omher (the desktop app under `apps/omher/`) may send, write, and import. This page is the full
statement of the boundary. `tests/test_omher_boundary.py` pins these sentences against the code, so a
behaviour change moves the code, this page and its test together. Glossary terms (omher, Elsewhere) are in `CONTEXT.md`; how the app is built
is in `apps/omher/README.md`.

## Rules

1. omher never patches Hermes. It reads Hermes' source-defined protocol and calls it as a client.
2. omher never writes to Slack, Discord or any other elsewhere session. It lists them and links to each thread in its own app, and nothing else.
3. omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`; the bridge has exactly one `prompt.submit` call site and it takes the main chat's id. Files the person attaches go to that same chat only, as bytes through Hermes' own `image.attach_bytes`, `pdf.attach` and `file.attach` (`chat.attach`, up to 100 MB each); the bridge never opens the person's files.
4. omher talks only to the person's own Hermes gateway on this machine, over loopback, through Hermes' own `connect_gateway`.
5. omher makes no LLM or API call itself. Every model call is Hermes'.
6. The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token the app made at launch.
7. The app starts the bridge as a child process and stops it when the app exits.
8. The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.
9. omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture (`assets/avatar.*`, through Hermes' `profiles.set_asset` when the gateway runs); the profile id, folder, config and sessions never change.
10. The only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`) with optional locks off, in folders the bot's own terminal runs used; omher never commits, checks out, pushes or edits a repository.
11. omher shows a file from disk only when the bot named it in a `MEDIA:` line of its own answer, in its main chat or an elsewhere session (`media.read`, read-only, files over 25 MB are not read); the desktop app opens only a file the bridge just served this way.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
