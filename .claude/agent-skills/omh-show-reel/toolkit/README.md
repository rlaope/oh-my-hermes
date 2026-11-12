# Optional local show-reel toolkit

This is executable **companion data**, not an OMH renderer command. Catalog,
install, update, routing and doctor only materialize/read its declared UTF-8
bytes. They never import/run these scripts or install production tools.

The engine (`assets/engine/engine.js`, `fx.js`, example `scenes.js`) is
revfactory/showreel at `64521220a2f8e91cb9894400c48c15b7f45205d6`, unmodified
below an attribution notice. The scripts are modified MIT derivatives of the same
revision. Copyright (c) 2026 Minho Hwang (revfactory). Full license:
`LICENSE.upstream`; per-file source hashes, classification and modification
notices: `upstream-manifest.json`. The craft references (`references/craft-*.md`)
are complete English translations of upstream's references. Font, brand,
recording and other asset rights are separate from the code license.

## Explicit host invocation

Resolve this directory from the loaded skill's base/returned `skill_dir`; read
this README and script help with ordinary file tools. Hermes may use
`read_file(<skill_dir>/toolkit/README.md)`; portable hosts use their own file
reader. No Hermes-only tool is needed to use the portable kit.

Prerequisites: Python >=3.11; Node, an **explicitly supplied** local
`puppeteer-core` dependency root, a Chrome or chrome-headless-shell executable,
FFmpeg with libx264 and FFprobe for capture. Optional: numpy for
`music_tools.py analyze`/`gap`, Pillow for `prep_images.py` and labelled contact
sheets, `swiftc` on macOS for cutouts. No npm/pip/font setup, CDN, provider
account or home font scan is performed; the only network-reaching scripts are the
opt-in provider scripts below, which run only when you invoke them. `preflight.py` reports
what is present. Use only explicit licensed local TTF/OTF fonts for rendering:
the cmap gate does not support WOFF/collections. A missing font/tool/glyph is
HOLD, never substitution. Only macOS capture execution has been exercised;
Linux/Windows render execution is HOLD/refused while installing the data stays
portable. Host smokes used chrome-headless-shell 145 and 152 with puppeteer-core
25.15.0.

```sh
S=toolkit/scripts
python $S/preflight.py --browser /explicit/chrome-headless-shell --dependency-root /explicit/node_modules
python $S/new_project.py PROJECT --ratio 16:9 --duration 60 --font /explicit/Display.ttf --font /explicit/Mono.ttf --language en
python $S/timeline.py PROJECT/script.json --music-analysis audio/music/analysis.json
node $S/render.mjs --dir PROJECT/reel --out PROJECT/qa/stills_s01 --stills 0.5,3.2,5.4 $TOOLS
node $S/render.mjs --dir PROJECT/reel --out PROJECT/qa/stills_all --every 0.5 $TOOLS
node $S/render.mjs --dir PROJECT/reel --out PROJECT/out/draft.mp4 --scale 0.5 $TOOLS
python $S/contact_sheet.py --video PROJECT/out/draft.mp4 --every 1 --out PROJECT/qa/sheet_draft.png
node $S/render.mjs --dir PROJECT/reel --out PROJECT/out/video.mp4 --sub 4 $TOOLS
python $S/synth_music.py toolkit/examples/music-spec.json --out PROJECT/audio/music/score.wav
python $S/music_tools.py analyze PROJECT/audio/music/score.wav
python $S/music_tools.py analyze PROJECT/audio/music/track.wav --bpm 174 --start 0 --window 40 --out PROJECT/audio/music/analysis.json
python $S/mix.py PROJECT/mix-spec.json --out PROJECT/audio/mix.wav --ffmpeg /explicit/ffmpeg
python $S/finish.py --video PROJECT/out/video.mp4 --audio PROJECT/audio/mix.wav --name "Title_60s" --outdir PROJECT/out/final
python $S/qa_check.py PROJECT/out/final/Title_60s.mp4 --audio-mode music-only --policy PROJECT/qa-policy.json --ffmpeg /explicit/ffmpeg --ffprobe /explicit/ffprobe
python $S/motion_check.py PROJECT/out/draft.mp4 --ffmpeg /explicit/ffmpeg --ffprobe /explicit/ffprobe --profile general --holds PROJECT/intentional-holds.json
python $S/motion_check.py PROJECT/out/final/Title_60s.mp4 --ffmpeg /explicit/ffmpeg --profile kinetic --endcard 3 --reference PROJECT/research/reference.mp4
```

`$TOOLS` stands for `--browser /explicit/chrome-headless-shell --dependency-root
/explicit/node_modules --ffmpeg /explicit/ffmpeg --ffprobe /explicit/ffprobe`;
add `--color swscale` when that FFmpeg has no zscale. Render outputs (videos,
still folders) and receipts must be new paths; initialization refuses an existing
project. A symlink as the file, its folder or that folder's parent is refused; the
only links accepted are macOS's own `/etc`, `/tmp` and `/var` into `/private`.
Never use secrets or unreviewed scripts.

## Project layout (upstream's)

`new_project.py` creates `research/`, `assets/{img,photos,gen,cutout,logo}/`,
`audio/{vo,music,sfx}/`, `qa/`, `out/` and `reel/` with `engine.js`, `fx.js`,
`index.html`, an empty `scenes.js` holding `REEL.config`,
`_example_scenes.js` (API example, not loaded), a stub `timeline.js` and
`fonts/fonts.css`. `fonts.css` declares only the `--font` files, with the family
and weight range read from each font, and points the `index.html` font tokens at
them. Edit the colour tokens per art direction; they are grey placeholders.

The renderer serves the project folder (the reel's parent), so scenes reach
`../assets/...` as upstream does, but only the files listed in `project.json`
`render_files` (an explicit POSIX allowlist, not a recursive serve root). When
you add an image, a split scene file or a library under `reel/lib/`, add its
project-relative path to `render_files` (and to `input_sha256` when you want the
digest pinned). `project.json` width, height, duration and fps must equal
`REEL.config`; the renderer compares them.

`project.json` can also declare `cuts`, at most 4096 strictly increasing numeric
seconds inside `(0, duration)`. Keep hard-cut scene boundaries at exactly these
times. The cut-aware `--sub`/`--shutter` sampler slides the shutter window inside
the shot of each output time (and shrinks it for a shorter shot), so samples
cannot blend across declared cuts. An output exactly at a cut belongs to the new
shot. With no cuts, centered shutter sampling is unchanged; success receipts
record the `cuts` count. No engine asset changes or half-frame cut shifts are
needed.

## Upstream command map

The craft references quote upstream's commands. Their equivalents here:

| Upstream | Here |
| --- | --- |
| `new_project.py <p> --ratio 16:9 --duration 60 [--fonts "Family:wght@..."]` | same, but fonts are `--font /explicit/file.ttf` (repeat); nothing is downloaded |
| `render.mjs --dir <p>/reel --out out/video.mp4 --sub 4 --format png` | same flags plus `$TOOLS`; PNG is the only capture format; no `--workers`/`--chunk`/`--fresh`/`--serve` |
| `render.mjs ... --stills t1,t2 --outdir qa/stills` or `--every 0.5` | `--stills t1,t2` or `--every 0.5` with `--out <new folder>`; frames are `000000.png...` and the receipt lists their times |
| `render.mjs ... --scale 0.5` (draft), `--from a --to b` | same; `--scale` above 1 supersamples and resamples to the page size |
| `timeline.py <p>/script.json --music-analysis ...` | same; `timing.json` (explicit cue graph) also works |
| `music_tools.py plan/analyze/splice/fit/gap` | same; `analyze`/`gap` need numpy |
| `synth_music.py music spec.json out.wav`, `synth_music.py sfx` | `synth_music.py spec.json --out out.wav` (sections with notes/energy/bpm, events kind/at) |
| `mix.py <p>/timeline.json [--hall]` | `mix.py mix-spec.json --out mix.wav` (stereo 16-bit WAV inputs; see Audio) |
| `qa_check.py out.mp4 --timeline ... --script ... --stt` | `qa_check.py out.mp4 --audio-mode <mode>`; no STT |
| `motion_check.py draft.mp4 --timeline timeline.json` | `motion_check.py draft.mp4 --holds intentional-holds.json` |
| `contact_sheet.py`, `finish.py`, `prep_images.py`, `preflight.py` | same flags plus optional `--ffmpeg`/`--ffprobe`; `finish.py` writes `_share.mp4`/`_poster.jpg` |
| `eleven.py ...`, `narrate.py script.json` | same, opt-in with your own `ELEVENLABS_API_KEY`; `--voice`/script.json `voice` and `language` are required (no default voice) |
| `codex_ref_image.sh out.png "scene" ref.jpg` | same, opt-in with your own signed-in `codex` CLI |
| codex-image and photoreal skills | not part of this kit; use them only if you installed them yourself |

## Opt-in provider scripts

`eleven.py` (ElevenLabs TTS, STT, SFX, music, voice lookup), `narrate.py`
(script.json narration lines with character alignment into `audio/vo/`) and
`codex_ref_image.sh` (reference-photo image generation through codex) reach a
provider. They are package data like everything here: OMH core never imports or
runs them, and nothing runs them on install, update or routing. They run only
when you invoke them, with your own credentials:

- `eleven.py` and `narrate.py` read the key only from `ELEVENLABS_API_KEY` in the
  environment (no `.env`, home or config lookup) and pass it to `curl` on stdin,
  never in argv, files or logs. Without it they print why and exit 2 having sent
  nothing. Credits are spent on your account; `narrate.py --only` regenerates
  single lines.
- `codex_ref_image.sh` needs your signed-in `codex` CLI on PATH and exits 2
  without it.
- Voice and language come from the brief's voice_policy and content locale; the
  scripts never choose them. Without a key the procedure falls back to the
  music-and-captions version: `synth_music.py` for music, on-screen text instead
  of narration, code-drawn or supplied visuals instead of generated images.
- `eleven.py sfx-kit` reads `assets/sfx_presets.json` (upstream's preset prompts).

## Capture contract

`window.__seek(seconds)` writes deterministic state synchronously (it may return a
promise for explicit readiness); `__ready` is true only after font/image
preparation; `__error` fails the adapter; `__meta` binds width/height/duration/fps.
The page loads with `?render=1`, so upstream's preview player stays hidden. The
host awaits seek/font/image readiness and compositor screenshot completion.
Running CSS/Web Animations are refused. Shuffled seeks must match decoded pixels
in the pinned tool/font environment; no cross-platform MP4 byte equality claim.

Serial capture only, piped to FFmpeg. `--sub N --shutter 0.5` averages N
sub-frame captures per output frame (upstream's 180-degree shutter); `--scale s`
sets deviceScaleFactor (s<1 draft at reduced size, s>1 supersampled back to the
page size); `--crf` defaults to 16, `--preset` to medium. Chrome runs with
`--disable-gpu-vsync --disable-frame-rate-limit`, so each capture waits on the
seek and the screenshot, not on the next vsync tick. Repeated renders with the
same settings stay byte-identical; a frame where two scenes overlap can differ
by a few code values from a render made before these flags. No workers, chunking,
stale resume or exists-only caching. Existing output/receipt refuses; a failure
writes `.failure.json` and keeps the partial folder. The loopback static server
serves only realpath-contained, symlink-free allowlisted files; sibling-prefix,
traversal, URL, encoded path, external request and range access refuse.
Page/font/image errors fail before final success; cancellation/timeout reaps local
children/browser and server. The default colour path converts sRGB primaries and
transfer to limited BT.709 with zscale; `--color swscale` does upstream's matrix
and range conversion. Full decode, frame count, dimensions and colour tags are
checked before the success receipt.

Bounds: 1/60..600 seconds; 1..60 fps; integral duration*fps <=36000; even
16..4096 dimensions; <=20 billion page pixels and <=100 billion captured pixels
(scale and sub included); <=512 input files, 32 MiB per input and 256 MiB total
snapshotted asset bytes; <=512 MiB per encoded output or still folder;
symlink-free regular JSON specs <=1 MiB; wall timeout 1..21600 s (default 1800).
Audio <=5,760,000 stereo sample frames; rates 8/16/24/44.1/48kHz. These are
resource policy bounds, not film defaults. No partial file or parse failure
becomes a measured zero/success.

## Locales

Content language follows `references/brief-and-locales.md`. Use explicit
language, direction and font families per run; literal tokens (URLs, commands,
IDs) stay isolated LTR runs. Arabic stays an intact shaped run; never reverse
strings. `project.json` `texts` optionally lists runs to glyph-check before
capture; every captured frame's visible text is checked against the declared
fonts' cmaps. Coverage, loaded fonts and representative renders do **not**
certify shaping, cultural copy, legibility or native-language correctness.

## Audio

`synth_music.py` supplies seeded section notes/energy/BPM and optional
`tick`/`boom`/`whoosh` events; it is a modest local score, not a licensed
orchestral track. `music_tools.py analyze` reads tempo, downbeats and hits from
any chosen track (`analysis.json`); `timeline.py script.json --music-analysis`
turns them into `barN`/`music.hitN`/`music.dropN` cues and writes `timeline.json`
plus `reel/timeline.js`. `analyze FILE --bpm HINT --start SECONDS --window SECONDS`
fits a bounded passage with a tempo/phase search within ±8% of the hint, without
slow-tempo folding. Without a hint it retains existing tempo behavior and adds
`alternatives` (half/double candidates within 60–200 BPM). Inspect `grid_strength`
(0..1), any `warning: "tempo hint disagrees with the track"`, and `drops` (up to
three time-ordered `{t, rise, bar}` rows; rise compares two bars after a downbeat
to one bar before it). Timeline drop cues shift by the music start offset just
like bar cues; `--start`/`--window` limit fitting, not source trimming.

Narration lines in `script.json` need per-line clips and
character alignment in `audio/vo/` first; without them timeline.py reports the
missing lines and exits 1. The opt-in `narrate.py` produces them with your own
key. An approved local recording can be supplied by hand in the same shapes:

- `audio/vo/<id>.mp3`: the line's clip (timeline.py decodes it with FFmpeg for
  the loudness envelope; mix it from a WAV conversion of the same clip).
- `audio/vo/<id>.align.json`: `{"characters": [...], "character_start_times_seconds": [...],
  "character_end_times_seconds": [...]}`, one entry per character of the line's
  `tts` text (spaces included), times in seconds from the clip start. Word timing
  and narration cues come from these arrays.
- `audio/vo/report.json`: `{"<id>": {"speech_start": 0.12, "speech_end": 2.84}, ...}`,
  the first and last spoken instants inside each clip.

Without character alignment, place lines and cues with `timing.json` instead
(explicit seconds/frames), which needs no narration files.

Mix accepts explicit stereo 16-bit PCM WAV at one declared sample rate; missing,
corrupt or mismatched audio refuses (convert explicitly first). Modes are
`muted`, `music-only`, `narration`, `narration+bed/SFX`. Required tracks never
disappear silently. Music gain automation is `[[seconds,dB],...]`; events use
`at` numeric or exact cue ID and `align:start|peak|end`. Speech energy ducks the
bed and restores it outside speech; stems survive. The sample limiter is **not**
a true-peak certificate. `--ffmpeg` measures LUFS/true peak; it does not
normalize. Measure the **final AAC** with QA and the chosen `--policy` JSON
(`lufs`, `true_peak`, `duration`, `fps`, `frames`, `max_bytes`, `width`,
`height`). A parse or decode failure is HOLD/nonzero.

## Independent acceptance

Use `references/kinetic-type.md` only when the selected concept is kinetic
typography for a hype launch or teaser, never for an explainer or evidence film.
For reference-led work, measure the approved reference first with the same motion
method, keep its hash and active range, then pass `--reference REF.mp4` when
checking the candidate. Reference metrics never alter the candidate verdict.

`motion_check.py VIDEO --ffmpeg PATH [--ffprobe PATH] --profile general|kinetic`
measures native fps (capped at 60), area-scaled 320x180 gray frames. `change_area`
is the fraction of pixels whose luma moved >24 since the prior frame. A still
frame is below 0.015; a cut is above 0.45 with an absolute mean-luma jump >18 or
area >0.6. Receipts include still share/runs, longest unannotated still, cuts per
10 s, mean change area, high-motion share (area >0.12), and flash-pair count.
These heuristics are not optical flow or a median-flow gate.

- `--profile general` (default): REVISE for an unannotated still run >1.0 s.
- `--profile kinetic`: REVISE for `still_share > 0.40` or an unannotated still
  run >0.6 s. Do not use it as a universal explainer pacing rule.
- `--endcard SECONDS` excludes the final seconds from **every** metric; the
  example `--endcard 3` is not a required end-card length.
- `--holds FILE` accepts authored intervals such as
  `[{"start":0,"end":1,"reason":"reading hold reviewed in storyboard"}]`.
  A nonempty reason is required. Only the covered part of a still run is exempt;
  holds do not exempt aggregate still share or flash review.
- Flashes are opposing mean-luma jumps >40 counted as pairs (up/down or down/up),
  not individual changes. `max_flashes_per_s` is the largest pair count in a
  one-second window. A ground flip without a return is not a flash. Both profiles
  REVISE with `flash_review_required` when that count is >3. Brightness heuristics
  never certify photosensitivity or accessibility safety.

Motion JSON binds `artifact_sha256` to `profile`, `metrics`, `policy`, `issues`,
`limitations` and `artistic: "not_observed"`. `--reference` adds a reference path,
hash and metrics. A freeze needs review, not a post-hoc intentional-hold label.
Strict issues exit nonzero.

Technical QA binds SHA256 and full decode to measured checks. Put delivery
constraints in the JSON passed to `qa_check.py --policy`, including
`max_h264_level` and `hardware_decode` when required; these are policy keys, not
standalone CLI flags. For example:

```json
{"max_h264_level": 42, "hardware_decode": true}
```

`max_h264_level` checks ffprobe stream `level` (42 for Level 4.2, 52 for Level
5.2; choose for the intended 1080p/4K delivery). A non-H.264 stream fails this
policy; measurements add `h264_level`. With `hardware_decode: true`, macOS fully
decodes using FFmpeg `-hwaccel videotoolbox` and any error line is REVISE. On
other OS the check is HOLD, "not observable on this host", so overall cannot be
PASS. Software decode and level compliance alone do not certify target playback.

The mix report adds `buried_hits: [{"at": 1, "file": "hit.wav", "sfx_db": -18,
"bed_db": -12}]` when a placed SFX's first 100 ms RMS is below the music bed in
the same interval, after bed automation and ducking. No SFX or muted mode yields
`[]`. This is a diagnostic, never automatic gain adjustment: review cue and level
choices, edit the authored mix, and remeasure final AAC. It is not listening.

A technical PASS never fills artistic, full-speed playback, listening, STT or
native-language approval. Open every contact sheet you make and look at it.
Critique every segment (keep/fix/rebuild), rebuild the weakest with before/after
evidence and both cut boundaries, and review the final encoded result. Reject
repeated headline/card/rail grammar even when all technical checks pass. Delivery,
receipt and public publication remain separate observations.
