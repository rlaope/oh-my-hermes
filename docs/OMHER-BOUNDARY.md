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
10. omher runs one installer, and only when the person presses Install on the first-run screen that appears because Hermes is missing: OMH's own one-line installer with `omher@beta` and `OMH_WITH_DESKTOP=0` (`curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta` on macOS, the `install.ps1` equivalent on Windows), which installs Hermes with its official installer and then oh-my-hermes. The command is fixed in the shell; nothing from the page reaches it.

## What this does not claim

omher is not an execution surface for OMH workflows, and none of OMH's routing, handoffs or evidence run
through it. These rules describe the code in this repository; they are not a sandbox, and an allowed Hermes
call made with other arguments is Hermes' to answer.
