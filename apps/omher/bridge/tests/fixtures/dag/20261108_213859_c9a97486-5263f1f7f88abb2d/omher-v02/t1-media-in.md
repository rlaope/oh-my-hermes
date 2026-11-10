# T1 media in: handoff

Status: **done**. All VERIFY gates passed. One commit on `feat/omher-v02-media` (wt `v02-media`). Not pushed.

## Commit
- `66a5bb11d` feat(omher): show files the bot sends (MEDIA: lines) as images, video, audio and file cards (signed-off)

## What was built (files)
- `apps/omher/src/chat/parts/mediaLines.ts` (+ `mediaLines.test.ts`): `splitMedia` takes only whole `MEDIA:<abs path>` lines out of the text and skips fenced code. It accepts optional quotes/backticks and `/`, `~/`, `C:\` anchors. Also kind by extension (image png/jpg/jpeg/gif/webp; video mp4/mov/webm/m4v; audio mp3/m4a/wav/ogg; anything else, HEIC included, is a file), plus name and size labels.
  - The file is named `mediaLines.ts`, not `media.ts`, because `media.ts` would collide with `Media.tsx` on a case-insensitive filesystem.
- `apps/omher/src/chat/parts/Media.tsx` + `media.css`:
  - `MediaList` renders the files in order.
  - Image tile: max 360×360, object-fit cover, radius 8. Clicking opens a lightbox portaled to `<body>` (full-window dim, image fitted, Esc or click closes, wheel zooms 1–4×).
  - `<video controls preload="metadata">` from a blob URL, width 420.
  - Compact `<audio controls>`.
  - 220px file card: ext badge, name, size, "Open". "Show in Finder"/"Show in Explorer" appears only in Tauri.
  - Loading skeleton while reading; on error a "Couldn't load file · name" line.
- `Bubble.tsx`: renders the remaining markdown, then the media. While streaming it only hides the lines (no reads mid-stream).
- `Timeline.tsx`: passes the bot name to the bubble. A ResizeObserver keeps the thread pinned to the bottom when media loads.
- `sidebar/BotRow.tsx`: the preview strips MEDIA lines. A media-only answer shows its file names.
- `src/lib/openMedia.ts`: invokes `open_media` in Tauri; does nothing in the browser/e2e.
- `src/lib/protocol.ts` and `src/state/store.ts`: the `media.read` op type, `MediaFile`, and a `readMedia` action.
- Bridge `bridge/omher_bridge.py`:
  - `media_paths`: same parser as the UI.
  - `media_named`: state.db through `ro_uri`, assistant rows only, sessions = title `Bot Chat` OR source not in LOCAL_SOURCES/subagent/oneshot (the main chat plus elsewhere), newest 50 rows containing the path, then an exact line match.
  - `media_file`: absolute only; refuses missing files, directories, and symlinks whose target leaves the link's own directory.
  - `read_media`: returns `{path,name,mime,size,data_base64}`, or `too_big:true` above 25 MB without opening the file.
  - `op_media_read` is registered as `"media.read"`. Anything not allowed returns `not_found`.
  - No new subprocess, so `_git` is still the only subprocess user.
- Rust:
  - `src-tauri/src/bridge.rs`: the stdout reader parses `OMHER_MEDIA_SERVED {"path":…}` lines into a served set (capped at 2000).
  - `src-tauri/src/lib.rs`: new command `open_media(path, reveal?)` → `media_target` (served AND absolute AND still a file) → `tauri_plugin_opener::open_path` / `reveal_item_in_dir`.
  - Tests: `open_media_refuses_paths_the_bridge_did_not_serve`, `media_line_names_one_absolute_file`, `only_served_media_is_known`.
- `docs/OMHER-BOUNDARY.md`: rule **11** covers `media.read` and `open_media`.
  - `tests/test_omher_boundary.py`: pins the sentences, raises the rule-count cap from 10 to 11, and adds `test_media_read_checks_the_bots_own_messages_read_only`.
- Mock and e2e:
  - `e2e/mock-bridge.mjs`: the default bot (Hermes) gets a seeded answer with 3 MEDIA lines, plus a `media.read` op serving `e2e/fixtures/media/` (chart.png 9.5 KB, clip.mp4 7.8 KB / 2 s, built with ffmpeg; report.zip 136 B).
  - `e2e/media.spec.ts` has 4 tests:
    - tiles render with no literal `MEDIA:` text; tile ≤360 with cover and radius 8; video readyState ≥1 and ≤420 wide; card name, size and 220px width
    - lightbox fills the window; Esc closes it; a click closes it
    - not_found for an unnamed path or another bot; a missing file shows "Couldn't load file"
    - screenshots
  - `bridge/tests/test_bridge.py` class `Media`:
    - served: main chat, elsewhere, symlink inside its folder
    - not_found: user message, cli session, subagent, prose (not a whole line), fenced code, symlink escape, directory, never named
    - too_big without the file being opened (spy on `open`)
    - state.db mtime unchanged
    - parser parity with the UI

## Decisions (made within the brief)
- **`media.read` takes an optional `info: true`**: it returns name/mime/size without bytes. File cards use it, so a 20 MB zip is never base64'd just to print its size. Bytes are only sent for image, video and audio.
- **How `open_media` knows "the paths the bridge just served"**: the bridge prints one `OMHER_MEDIA_SERVED {"path": real}` stdout line per successful read (only when run as the app's child, `announce_media`). The Rust reader keeps that set. The UI cannot add to it.
- The bridge returns the resolved real path. The UI passes that path to `open_media`.

## VERIFY (literal tails)
- `pnpm typecheck && pnpm test` → `$ tsc -b --noEmit` … `Test Files  4 passed (4)` / `Tests  39 passed (39)`
- `~/.hermes/hermes-agent/venv/bin/python -m unittest discover -s bridge/tests` → `Ran 56 tests in 0.880s` / `OK`
- `OMHER_PORT=5411 OMHER_MOCK_PORT=5412 /usr/bin/lockf -k …/omher-heavy.lock pnpm exec playwright test e2e/media.spec.ts --reporter=line` → `4 passed (4.5s)`
- Extra regression run, same ports: shell, elsewhere, appearance, activity, mock and usability specs → `39 passed (50.3s)`
- `PYTHONPATH=tests …python -m unittest tests.test_omher_boundary` (repo root) → `Ran 9 tests in 3.629s` / `OK`
- `git diff --check` → clean
- `(cd src-tauri && lockf … cargo test)` → `test result: ok. 22 passed; 0 failed` (includes the 3 new tests) / `EXIT 0`
- Windows: `cargo check --target x86_64-pc-windows-msvc` (CARGO_TARGET_DIR=…/omher-wincheck-t1) → `Finished \`dev\` profile [unoptimized + debuginfo] target(s) in 48.17s` / `EXIT 0`
- Logs: `~/.hermes/profiles/kami/cache/scratch/omher-t1-{cargo,win,verify}.log`

## Screenshots
- `~/.hermes/profiles/kami/cache/scratch/omher-v02/T1-media-dark.png`
- `~/.hermes/profiles/kami/cache/scratch/omher-v02/T1-lightbox-dark.png`
- `~/.hermes/profiles/kami/cache/scratch/omher-v02/T1-media-light.png`

## Open / not done
- I did not run the real Tauri app by hand, so "Open" / "Show in Finder" on a real file is untested beyond the Rust unit test and the Windows compile.
- I did not try `media.read` against the live kami state.db through a running bridge. The query was timed by hand on the real 357 MB db: about 0.6 s cold.
- The full e2e suite was not run; that's T9's job. Specs that touch the timeline, bubbles or the default bot all passed (list above).
