# omher on Linux

omher ships for Linux x86_64 as an AppImage (one file, runs on most distributions with glibc 2.35 or newer, the
Ubuntu 22.04 build host's) and a `.deb`. Both come from the `omher-v*` releases on GitHub, next to the macOS and
Windows builds.

## Install

One command, the same as on macOS:

```sh
curl -fsSL https://omher.app/omher | sh
```

It installs Hermes and oh-my-hermes when they are missing, then downloads `omher-<version>-linux-x64.AppImage`,
checks it against the release's `SHA256SUMS.txt`, puts it at `~/.local/bin/omher` (`OMH_APP_DIR` changes the
folder), and writes `~/.local/share/applications/omher.desktop` plus the icon so omher shows up in the app menu.
On a machine that is not x86_64 the app step is skipped with a note.

By hand: download the AppImage from the release, `chmod +x` it and run it.

## What it needs

- **WebKitGTK 4.1** (`libwebkit2gtk-4.1-0`), the system web view Tauri uses on Linux. GNOME and KDE desktops on
  Ubuntu 22.04+, Debian 12+, Fedora 37+ and Arch have it.
- **FUSE 2** to mount the AppImage (`libfuse2`, or `libfuse2t64` on Ubuntu 24.04). Without it, run
  `./omher --appimage-extract-and-run`.
- Hermes Agent on the same machine. omher looks for Hermes' Python at `~/.hermes/hermes-agent/venv/bin/python`
  (or `HERMES_HOME`, or `OMHER_HERMES_PYTHON`), exactly as on macOS.

## Updates

The update button in the sidebar works on Linux too. The updater reads the same `omher-latest/latest.json`, whose
`linux-x86_64` entry points at the release's AppImage and its `.sig`; it installs only a build signed with the
key pinned in `tauri.conf.json`, then replaces the running AppImage file in place and restarts. `latest.json`
carries no `.deb`, so a `.deb` install is updated by installing the next release's `.deb` by hand
(`sudo apt install ./omher-<version>-linux-x64.deb`).

## What is different on Linux

- **Links** open with `xdg-open` (then `gio open`, `kde-open`). Inside an AppImage omher runs it without the
  AppImage's bundled-library environment (`LD_LIBRARY_PATH`, `XDG_DATA_DIRS` and other entries under the mounted
  image), because the host's opener and browser crash or pick the wrong handler with it
  (`apps/omher/src-tauri/src/appimage.rs`).
- **Terminal agents** (Claude Code, Codex, pi, ...) are found on `PATH`, then `~/.local/bin`, `~/.bun/bin`,
  `~/.cargo/bin`, `~/.npm-global/bin`, `~/.volta/bin`, `~/.local/share/pnpm`, `/usr/local/bin` and the newest
  nvm Node (`~/.nvm/versions/node/<v>/bin`), the same search as on macOS minus the app-bundle folders.
- **The bridge** ships inside the AppImage at `usr/lib/omher/bridge/omher_bridge.py` and is found through Tauri's
  resource folder, as on the other platforms.

## Troubleshooting

- *Blank window*: some GPU drivers need `WEBKIT_DISABLE_DMABUF_RENDERER=1 omher`.
- *Nothing happens on a link click*: check `xdg-open https://omher.app` works in a terminal; omher uses the same
  handler.
- *"AppImages require FUSE"*: install `libfuse2` (see above) or use `--appimage-extract-and-run`.
