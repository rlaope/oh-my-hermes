# omher

omher is a desktop app for your Hermes bots, on macOS and Windows. Each Hermes profile is one bot. Each bot has one main
chat, and the app shows what that bot is doing in its other sessions (Slack, Discord, Telegram, cron)
read-only. Under the bots, SESSIONS starts a terminal agent (Claude Code, Codex, oh-my-hermes, pi, oh-my-pi) in a
folder you pick and runs it inside the window, as if you had typed `claude` or `codex` in a terminal. It is part of
this repository but is not part of the `omh` Python package.

Boundary: [`docs/OMHER-BOUNDARY.md`](../../docs/OMHER-BOUNDARY.md).

## Install

**One command (beta).** It installs Hermes Agent and oh-my-hermes if they are missing, then omher
(macOS and Windows; Linux gets Hermes and OMH only). Download buttons are on [omher.app](https://omher.app/).

```sh
curl -fsSL https://omher.app/omher | sh
# same as: curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta
```

```powershell
irm https://omher.app/omher.ps1 | iex
# same as: & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta
```

The installer copies omher into `/Applications` (or `~/Applications`) on macOS and runs the Windows installer
silently for your user. `OMH_WITH_HERMES=0` skips installing Hermes; `OMH_WITH_DESKTOP=0` skips the app.
Without `omher@beta` the one-liner installs only the `omh` command, as before.

![The omher desktop app in dark mode: a bot list on the left, and a chat with the bot Kami that reports a nightly digest from Discord, picks up a Slack thread about 502 errors, runs four steps and answers with the fix](../../assets/omher-in-use-dark.webp)

**If you install the app first**, it checks for Hermes on its first launch. When Hermes is missing it shows
"omher needs Hermes and oh-my-hermes" with an **Install** button that runs the same one-liner without the app
(`OMH_WITH_DESKTOP=0`), shows the output, and opens your bots when it finishes. omher needs Hermes only; OMH comes
along because the installer sets both up. This is the only program omher runs besides its bridge
([boundary rule 12](../../docs/OMHER-BOUNDARY.md)).

### Download

omher is open source and ships as plain installers on the
[GitHub Releases page](https://github.com/rlaope/oh-my-hermes/releases?q=omher&expanded=true) (tags `omher-v*`).
There is no App Store build. It runs on [Hermes Agent](https://github.com/NousResearch/hermes-agent) on the same
machine and finds Hermes' Python on its own (see "Where omher looks for Hermes" below); when it finds none, the
first launch offers to install it, as described above.

**macOS (11 or later).** Download `omher-<version>-macos-arm64.dmg` (Apple Silicon) or `-macos-x64.dmg` (Intel),
open it and drag omher into Applications. The app is ad-hoc signed, not notarized, so the first launch needs
one extra step: right-click omher in Applications, choose **Open**, then **Open** again. After that it opens
normally. If macOS still says the app "is damaged", clear the download flag once:

```sh
xattr -dr com.apple.quarantine /Applications/omher.app
```

**Windows 10/11 (x64).** Download `omher-<version>-windows-x64-setup.exe` (installs for your user, no admin) or
the `.msi`. The installer is not code-signed, so SmartScreen may say "Windows protected your PC": choose
**More info**, then **Run anyway**. The installer fetches Microsoft's WebView2 runtime if it is missing.

Check a download against `SHA256SUMS.txt` on the same release:
`shasum -a 256 <file>` (macOS) or `certutil -hashfile <file> SHA256` (Windows).

### Where omher looks for Hermes

1. `OMHER_HERMES_PYTHON`, if set (any Python that can import Hermes).
2. `HERMES_HOME/hermes-agent/venv` (then `.venv`), if `HERMES_HOME` is set.
3. The installer's default home: `~/.hermes/hermes-agent/venv/bin/python` on macOS and Linux,
   `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe` on Windows.

## Architecture

```
UI (React in a Tauri window)  ⇄  bridge (Python, loopback WebSocket)  ⇄  the person's own Hermes gateway
```

- **UI** (`src/`): talks only to the bridge, through the protocol in `src/lib/protocol.ts`.
- **Shell** (`src-tauri/`): starts the bridge with Hermes' own Python, reads its `OMHER_BRIDGE_READY` line,
  hands the UI a `ws://127.0.0.1:<port>/?token=<random>` URL, and stops the bridge when the app exits. If the
  bridge cannot start, the UI shows the error with a Retry button; if the reason is that Hermes is missing, it
  shows the first-run Install screen instead (`src-tauri/src/setup.rs` holds its one fixed command).
- **Bridge** (`bridge/omher_bridge.py`): uses Hermes' `connect_gateway`, one connection per profile. It binds
  127.0.0.1 only and refuses any connection without the launch token.
- **Mock bridge** (`e2e/mock-bridge.mjs`): the same protocol, scripted, for the Playwright tests.
- **Sessions** (`src-tauri/src/sessions.rs`, `src/sessions/`): the SESSIONS `+` lists the agent programs found on
  `PATH` and in the usual install folders (`~/.local/bin`, Homebrew, npm/pnpm/bun globals, `%APPDATA%\npm`), asks
  for a folder, and starts the program in a pseudo-terminal (`portable-pty`: a Unix PTY on macOS, ConPTY on
  Windows) drawn with xterm.js. The UI sends only an agent id (`claude`, `codex`, `omh`, `pi`, `omp`, `grok`); the shell
  refuses anything else and never takes a command line or arguments. Closing a session or quitting the app stops
  the program. In a plain browser (dev, e2e) a mock host echoes what you type instead. A chat session's approvals
  and questions are asks like a bot's: they join the Needs-you strip and ⌘J (named by folder and agent), and the
  session row rings while a turn runs and shows the amber dot while it asks.

Rules the code keeps:

- **Read-only elsewhere.** `chat.send` reaches only the bot's main chat (the session titled `Bot Chat`). Other
  sessions are listed and their history read, never resumed, answered, interrupted or written to.
- **Loopback only.** The bridge listens on 127.0.0.1 and talks to the gateway Hermes itself runs on this machine.
- **No model calls of its own.** Every model call is Hermes'. omher has no API key and no HTTP client.
- **Sessions run only allow-listed agents.** Only when you start one, only `claude`, `codex`, `omh`, `pi`, `omp` or `grok`,
  with no arguments, in the folder you picked; stopped when the session is closed or the app quits.

## Develop

Needs Node, pnpm, Rust, and Hermes Agent installed (found as described above). Works on macOS and Windows; on
Windows run the commands in Git Bash or PowerShell.

```sh
pnpm install
pnpm dev                  # the UI alone, against VITE_OMHER_BRIDGE or ws://127.0.0.1:5308/?token=dev
node e2e/mock-bridge.mjs --port 5308   # the mock bridge for that
pnpm tauri dev            # the app: starts the real bridge from ./bridge
pnpm typecheck && pnpm test            # tsc, vitest
pnpm e2e                  # Playwright (chromium) against the mock bridge
(cd src-tauri && cargo test)           # the shell's Rust tests
(cd src-tauri && cargo test real_agents_print_their_version -- --ignored --nocapture)  # `claude/codex --version` through the PTY
python -m unittest discover -s bridge/tests -v   # bridge tests with a FakeGateway; needs no Hermes
pnpm tauri build --debug --bundles app # a debug .app in src-tauri/target/debug/bundle/macos/
pnpm tauri build --bundles dmg         # macOS release .dmg (ad-hoc signed)
pnpm tauri build --bundles nsis,msi    # Windows release installers (unsigned)
```

## Release

Bump `version` in `src-tauri/tauri.conf.json` (and `src-tauri/Cargo.toml`, `package.json`), merge, then push a
tag `omher-v<version>`. `.github/workflows/omher-release.yml` builds the macOS (arm64, x64) and Windows (x64)
installers, writes `SHA256SUMS.txt` and attaches everything to a GitHub Release of that tag. No Apple Developer
or Windows signing certificate is involved: macOS builds use an ad-hoc signature (`signingIdentity: "-"`).
