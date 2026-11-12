# Selected host-tool recipe and optional companion

## Companion decision

This release ships an optional local companion, NOT a core render command: the
upstream engine (`engine.js`, `fx.js`, example `scenes.js`) unmodified below its
attribution notice, upstream-derived scripts, and an OMH capture adapter that keeps
upstream's render quality flags. Read `toolkit/README.md` with a file reader
relative to the loaded skill directory (`skill_dir` on native Hermes); portable
hosts use their own base directory and ordinary file tools. No companion import,
process, socket, dependency setup or font download occurs during OMH discovery,
projection, installation, update, routing or doctor.

The method prose is original; the `references/craft-*.md` pages are complete
English translations of the upstream references. The engine, motion/audio/capture
helpers and QA tools are MIT files from revfactory/showreel revision
64521220a2f8e91cb9894400c48c15b7f45205d6, Copyright (c) 2026 Minho Hwang
(revfactory). Every distribution carries `toolkit/LICENSE.upstream`, per-file
notices and `toolkit/upstream-manifest.json` with original/local hashes and
modification status. Preserve all of them in the source kit. Asset/font/voice
rights are independent. The engine is upstream's; the capture adapter is not
upstream's Playwright renderer (no workers, chunks or resume).

Explicit operator invocation, after confirming a new output workspace and local
prerequisites (paths are examples, never auto-run):

```sh
python toolkit/scripts/new_project.py NEW_PROJECT --font /approved/font.ttf --ratio 16:9 --duration 60 --language en --direction ltr
python toolkit/scripts/timeline.py NEW_PROJECT/script.json --music-analysis audio/music/analysis.json
node toolkit/scripts/render.mjs --dir NEW_PROJECT/reel --out NEW_PROJECT/out/draft.mp4 --scale 0.5 --browser /approved/chrome-headless-shell --dependency-root /approved/node_modules --ffmpeg /approved/ffmpeg --ffprobe /approved/ffprobe
node toolkit/scripts/render.mjs --dir NEW_PROJECT/reel --out NEW_PROJECT/out/video.mp4 --sub 4 --browser /approved/chrome-headless-shell --dependency-root /approved/node_modules --ffmpeg /approved/ffmpeg --ffprobe /approved/ffprobe
python toolkit/scripts/contact_sheet.py --video NEW_PROJECT/out/draft.mp4 --every 1 --out NEW_PROJECT/qa/sheet_draft.png
python toolkit/scripts/synth_music.py toolkit/examples/music-spec.json --out NEW_PROJECT/score.wav
python toolkit/scripts/mix.py NEW_PROJECT/mix-spec.json --out NEW_PROJECT/mix.wav --ffmpeg /approved/ffmpeg
python toolkit/scripts/qa_check.py NEW_PROJECT/final.mp4 --audio-mode music-only --ffmpeg /approved/ffmpeg --ffprobe /approved/ffprobe
```

These flags are the companion's tested adapter, not a new OMH command. Initialization
preserves an existing authored project by refusing it. The exact-frame adapter is
explicitly Puppeteer (not Playwright), serial capture piped to FFmpeg, allowlisted
loopback assets served from the project root, no external requests or range access,
no resume/chunks/workers; `--sub N` averages N sub-frame captures per frame (shutter
blur), `--scale` above 1 supersamples back to the page size, CRF defaults to 16.
Without FFmpeg zscale pass `--color swscale` (upstream's matrix/range conversion).

Declare hard cuts in the project root's `project.json`: `"cuts": [1.5, 3.0]`,
for example, is valid only when both times fall strictly inside the duration.
`cuts` must contain strictly increasing numbers in `(0, duration)`, at most 4096;
invalid declarations refuse before capture. Keep scene boundaries and this array
in sync. With `--sub N --shutter S`, samples belong to the shot containing output
time `t`: `[last cut <= t, next cut > t)`. The cut-aware shutter slides its window
inside that shot and shrinks it only when the shot is shorter than the window;
no sample crosses a declared cut. Without cuts the existing centered shutter
sampling is unchanged. A success receipt records the `cuts` count, not a visual
review of the transitions. This replaces the old half-frame hard-cut workaround;
the engine assets themselves are unchanged.

Partial frames are never a final success. Tested capture execution is macOS with explicitly supplied
Chrome headless-shell; Linux/Windows execution is HOLD, while installation of the
text data stays portable. Full Chrome headless surface capture stalled on the
observed host; missing tool/font/glyph and untested paths must not be certified.

Use the engine contract in `references/motion-techniques.md` with the full API in
`references/craft-engine.md` and verified technique code in
`references/craft-techniques.md` and `references/craft-techniques-2.md`,
audio/stem contracts from
`references/audio-production.md`, and composition/revision gates from
`references/art-direction.md`. `reel/_example_scenes.js` teaches the API, not the
film's storyboard, and an example never fulfills a commissioned film.
Capture receipts bind exact input/font/tool versions, seek times, cleanup, decoded
frames and converted color. Keep technical versus artistic/playback/listening
verdicts separate; source code and measurements are not hearing or artistic review.

## Preflight and scope

Record `show_reel_renderer_handoff/v1`: selected executor, exact versions and paths,
observed capabilities, approved cwd/input/output roots, dimensions/fps/duration,
network/asset policy, seed/time semantics, font readiness, commands, timeout,
cancel/reap method, chunk/resume policy and failure log references. Probe through
the exact interpreter/Node/browser invocation that will render, not another tool
context. Browser/Node/FFmpeg are optional host dependencies, never core packages.
Do not scan accounts, credentials or another profile; no API keys needed here.

An unavailable renderer returns storyboard/source handoff and HOLD on a requested
video. Missing font, pageerror, timeout, failed subprocess or partial frames must
surface as failed/partial evidence; never silently retry to an unrelated renderer.
No promised voice, translation or Arabic support without observed exact capability.

## Implement a deterministic local scene with observed host tools

1. Author an isolated local HTML/Canvas project. Expose `seek(tSeconds)` as a pure
   function of absolute time, fixed seed, approved assets and dimensions. A paused
   timeline may be used; no wall-clock delta, random unseeded values, external
   fonts, CSS animation clock, async race or network asset. Wait for local images
   and `document.fonts.ready`; render representative script runs before capture.
2. Capture exact frame `i` at `t=i/fps`, for `i=0..N-1`, with documented rounding
   of duration×fps. For Canvas, export the actual `toDataURL('image/png')` surface
   after synchronous draw; HTML needs a proven compositor screenshot barrier.
   Browser seek should update text and layout before that barrier. Record errors.
3. Seek 0, an interior time, end, then the same interior time out of order; compare
   decoded pixel hashes at identical times. Independent seeks must not depend on
   prior frames. A matching file hash alone is weaker than decoded pixel equality.
4. If chunking is needed, give chunks disjoint half-open frame ranges `[a,b)`, same
   global time base/seed/assets and one output owner. Resume only after recipe,
   asset, font and tool digests match and existing frames decode at expected
   dimensions. Missing/mismatched frames re-render; never concatenate partial
   files as success. Parallel/resume is unavailable until this is actually tested.
5. Encode a selected existing frame sequence with explicit container and color
   conversion. This example is for verified sRGB Canvas frames only; other input
   profiles need their own conversion. Agent/operator recipe (replace paths/rates):

```sh
ffmpeg -framerate 24 -i frames/%06d.png -an -vf 'scale=out_color_matrix=bt709:out_range=tv,colorspace=iall=bt709:itrc=iec61966-2-1:all=bt709:range=tv:format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709' -c:v libx264 -pix_fmt yuv420p -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 -movflags +faststart share.mp4
ffprobe -v error -show_format -show_streams -of json share.mp4
ffmpeg -v error -i share.mp4 -f null -
```

These are preparation examples, not auto-run commands or universal channel
compatibility. Explicitly confirm source color interpretation before conversion;
metadata labels alone do not prove correct color. Color transfer conversion and
frame metadata must survive the filter chain; encoder flags alone may leave
primaries/transfer unknown, so inspect the final ffprobe fields and decoded colors
rather than trusting command success. With voice/music, mix approved local audio
and measure loudness/true peak and sync; do not use `-an` then claim audio.
For requested GIF use an actual palette encode and inspect decoded timing/loop;
an MP4 renamed GIF is not a GIF. Do not install dependencies to make a recipe work
without permission. Keep browser profiles and temporary frames invocation-owned,
reap child processes on cancel/timeout, and retain receipts outside deleted homes.

## Timing first, only as needed

Choose muted, music-only or narration explicitly. Muted needs measured reading
and visual rhythm, no synthetic audio. Music-only needs rights and beat/cue timings.
Narration needs approved literal script plus separate pronunciation_text, licensed
voice/locale capability, cost/consent and measured utterance/word cues before scene
locking. Translation permission and native review remain separate. STT on real
speech can compare words/times, not certify pronunciation or replace listening.
