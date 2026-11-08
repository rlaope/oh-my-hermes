> Translated in full from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 `showreel/references/qa.md` (MIT, Copyright (c) 2026 Minho Hwang (revfactory); `toolkit/LICENSE.upstream`, provenance in `toolkit/upstream-manifest.json`). Read it for critique, the technical checklist, reading contact sheets, delivery report and production notes. `$S` is `toolkit/scripts` under the loaded skill directory. Commands here are upstream's; check the upstream command map in `toolkit/README.md` before running one. Content language follows `references/brief-and-locales.md`: Korean-first defaults apply only to Korean content, the craft bar applies to every locale; host install paths are placeholders here, upstream's default narration voice is named by role and chosen only through voice_policy, inline OMH notes mark where OMH policy overrides an upstream default, and the provider scripts are opt-in with the user's own key.

# Review and delivery

Script paths on this page use `S=<skill_dir>/toolkit/scripts`, where `<skill_dir>` is this skill's folder.

## Contents

- Review stages
- Critique
- Checklist
- What to check when viewing a sheet
- How to read the automated review (qa_check.py)
- Delivery: file names, report format, production notes

## Review stages

| Stage | When | What | Tool |
| --- | --- | --- | --- |
| 1. Material | Right after making images and cutouts | Hand or face anomalies, mixed-in text or logos, letterboxing, palette | `prep_images.py --sheet` |
| 2. Style frames | Right after making 1 to 2 representative frames per segment | Is it good enough to use as a poster, do the segments look like different works, did "cliche screen" elements get in without a reason | `render.mjs --stills` + `contact_sheet.py --dir` |
| 3. Per-scene stills | Each time a scene is written | start+0.5 / cue+0.4 / end-0.6 seconds | Same |
| 4. Draft critique | After all scenes exist, and on every fix | The eight questions in "Critique" below, the whole flow at 1-second intervals, frame strips of key moments, scene boundaries ±3 frames, frozen stretches and large motion | `render.mjs --scale 0.5` + `contact_sheet.py --every 1` / `--around` + `motion_check.py` |
| 5. Audio | Right after the mix | Per-line narration vs background dB, LUFS | `mix.py` table |
| 6. Finished cut | Right after finishing | Spec, loudness, luminance, freezes, final sheet | `qa_check.py --audio-mode MODE` (no STT in this kit) |

Repeat stages 2 to 4 until every segment is "keep" in the critique and the checklist below passes. Always open the sheets with Read. For a revised scene, pull stills at the same times again and compare before and after. If you do not compare the same frames when changing parameters, you end up swinging between "too dark <-> blown out to white".

Interval standard: 0.5 seconds for a 15 to 20-second video, 1 second for 60 seconds, 2 seconds for 100 seconds, 3 seconds for 5 minutes. For stretches where ghosting or blank screens are suspected, look frame by frame at 0.1-second intervals or with `--around`. If a cell of an interval sheet lands mid-transition and looks blurry, it may be a transition frame rather than a defect, so pull the times before and after again with `--times` to confirm.

## Critique

The technical checklist finds defects. The critique judges whether this video shows "how amazing a motion graphics designer" this is. Do it every time a draft is rendered.

### Material to look at

1. A full sheet at 1-second intervals (`contact_sheet.py --video draft.mp4 --every 1`): the differences between segments and the overall flow
2. A frame strip of one key moment per segment: 12 to 20 frames at 0.033 to 0.1-second intervals (`render.mjs --every 0.033 --from <sec> --to <sec> --outdir qa/strip_sNN`, then `contact_sheet.py --dir`). Spacing, anticipation, settling, and overlap that still frames do not show are seen here
3. Segment boundaries ±3 frames (`--around`)

### Questions

| # | Question | If not |
| --- | --- | --- |
| 1 | If one frame of this segment is set next to a template video or another AI video, can it be told apart | Find the "cliche screen" elements from `craft-design.md` and remove them or change direction |
| 2 | Does each segment look like a different work (medium, palette, typeface, motion) | Re-decide the art direction of the weaker of two similar segments |
| 3 | Does each segment have a "how did they make that" moment | Re-set that segment's technical challenge |
| 4 | Is the form of Hangul used in the motion | Add a scene that uses jamo, strokes, the square syllable block, or weight |
| 5 | In the frame strip, does the motion show weight and material (anticipation, overshoot, overlap, follow-through) | Redesign the easing per element |
| 6 | Are the picture and the music in the same rhythm. Is not every beat given an event of the same size | Divide event sizes by beat, bar, and section |
| 7 | When flipping through the 1-second sheet from the start, is there a point where the next segment is predictable | At that point, change the next segment's medium or entry method |
| 8 | Which is the weakest segment in this video | (Answer every time) |

### Verdict and record

- For each segment, decide keep / fix / rebuild and write the reason in one line in `qa/critique_NN.md` (NN is the draft number).
- If the segment chosen in question 8 is not "keep", rebuild it with a change of direction rather than adjusting values. Put stills of a rebuilt segment side by side with the previous version at the same times and compare.
- Before the final render, at least once, give only the sheets, the frame strips, and the questions above to a subagent with no context of the making, and get its verdict. The purpose is to find problems the maker missed. The subagent returns that verdict in its response, and the main agent copies it into the same file.
- When every segment is "keep" and the checklist passes, move on to the final render.

## Checklist

Picture:

- [ ] The first 5 seconds look as designed in the "first 5 seconds" of `concept.md`. It does not start with an unintended blank frame
- [ ] There is time to read all text (Hangul 6 to 8 characters per second)
- [ ] The on-screen Korean copy (segment names, fictional commission names, end card text) has no translationese or awkward coinages
- [ ] Text is not cut off the screen and does not overlap other elements or subtitles (except intended crops)
- [ ] Hangul has not been replaced by the default gothic font (the font list in the render log, zoomed crops)
- [ ] Numbers, proper nouns, and titles are exactly the same as in `research.md`
- [ ] No screen is frozen for more than 1 second (except the end card and intended holds). It exceeds the `motion_check.py` standards (frozen screen ratio, large motion p90)
- [ ] Exits do not end with only a fade
- [ ] Scene boundaries have no blank frames, ghosting, or leakage from the previous scene
- [ ] Flashes do not cover the screen in gray or white (opacity ≤ 0.15, no more than 3 per second)
- [ ] Within a segment, the art direction of `concept.md` is kept. The same transition is not used three times in a row
- [ ] The name and CTA on the end card are large enough (48px or more) and have time to be read
- [ ] No other company's logo or real person's face was drawn or generated. The brand of a fictional commission does not imitate a real company

Sound:

- [ ] (If there is narration) on every line the narration is 9dB or more louder than the background (`mix.py` table)
- [ ] If reverb was put on the narration, the "speech tail reverb" in `mix.py` is ✓ (-32dB or below)
- [ ] In the finished-mix STT every line is heard correctly. Especially names, numbers, and years
- [ ] On-screen hits and sound effects are on the same frame. Impact sounds do not cover key words
- [ ] -14 LUFS ±1, true peak ≤ -1 dBFS

Spec:

- [ ] H.264 / yuv420p / tv range / BT.709, frame count = length × fps
- [ ] Audio AAC 48kHz, faststart
- [ ] The share file is a size suitable for sending over a messenger (around 25MB for 60 seconds)

## What to check when viewing a sheet

These are defects that actually occurred in past productions.

- A stretch where the screen goes empty for the 0.3 seconds the camera moves
- Ghosting where a previous element remains at the edge of the screen
- Two elements brushing past and overlapping during interpolation
- Scene leakage: an image from a finished scene remains behind the next scene
- A counter so fast the numbers cannot be read, or negative progress showing as "-2 lines"
- A line crossing text: give the text a background-colored halo (text-shadow) or move the line
- The composition leaning upward so the bottom 40% of the screen is empty
- Subtitles hiding graphics (there was a case that showed up only in the finished MP4)
- A diagram drawn in code reading as an unintended shape (e.g. the papillary muscle in a heart cross-section looking like an eye)
- The end card too small, the CTA the smallest text

## How to read the automated review (qa_check.py)

```bash
python3 $S/qa_check.py out/<name>.mp4 --audio-mode music-only --policy qa-policy.json --ffmpeg /explicit/ffmpeg --ffprobe /explicit/ffprobe   # this kit: --audio-mode is required; no --timeline/--script/--stt
```

- **Excessive flashing**: more than 3 sudden brightness changes per second. Reduce the flash intensity and count (risk of photosensitive seizures).
- **Motion**: look at the frozen screen ratio, freezes longer than 1 second, and large motion p90 (it catches freezes even with film grain). In a frozen stretch, a new event (an entrance, a rearrangement, a camera move) or a moving surface behind the scene works better than a subtle drift. If p90 is low, there are too few moments where the whole screen changes greatly (composition change, large move, medium change). What to fill it with is decided by that segment's art direction.
- **Dark stretch**: catches only empty screens that are dark and have almost no bright elements. Normal scenes with a dark mood are not flagged.
- **White frame**: counts only bright frames that pop in for under 0.3 seconds between dark screens (an excessive flash). A segment designed on a bright background is only noted for reference as a "bright stretch".
- **STT ✗**: a number differs or similarity is below 0.85. Fix it when the same result comes up twice. The fix order is in "Narration generation and pronunciation verification" in `craft-audio.md`.
- View the final sheet (`qa/final_sheet*.png`) with Read. The automated checks do not catch overlapping text, font substitution, or typos.

## Delivery

### File names

`<title>_<length>s.mp4` (master), `<title>_<length>s_share.mp4`, `<title>_<length>s_poster.jpg`, `<title>_<length>s.srt`. The title may be in Hangul (e.g. `이훈희_CIPO_쇼릴_60s.mp4` (Lee Hoon-hee_CIPO_showreel_60s.mp4)). When making several lengths, change only the length.

### Delivery report (final message)

Put the absolute paths first so the user does not have to ask again "where is the video file?".

```markdown
## Done: <title> (60 seconds)

| File | Path | Size |
| --- | --- | --- |
| Master | /…/out/<title>_60s.mp4 | 68MB |
| Share | /…/out/<title>_60s_share.mp4 | 24MB |
| Poster | /…/out/<title>_60s_poster.jpg | |
| Subtitles | /…/out/<title>_60s.srt | |
| Production notes | /…/production-notes.md | |

Preview (browser): `node <S>/render.mjs --dir <project>/reel --serve`

### Concept
- The chosen concept in one sentence, why it was chosen, and the discarded candidates

### Structure
| Time | Segment | Medium / art direction | Narration | Picture |
…

### Decisions made
- What Claude decided (mood, length, aspect ratio, whether to narrate, etc.) and why
- Segments rebuilt in critique and why (`qa/critique_*.md`)
- What was reflected differently from the request (such as a career order that differs from the research) and why
- Features that could not be used and the fallback path (e.g. Music API unavailable -> synthesized music)

### Check before publishing
- Permission to use press photos, photos where signatures or official seals are visible
- Single-source facts, wording that becomes wrong after a date passes (early bird, etc.)
- People in AI-generated images are fictional people
- Sound: Claude cannot hear sound and checked only by numbers (loudness, STT, narration vs background). Ask them to listen once on speakers or earphones

### When fixing
- Wording or narration: edit script.json -> narrate.py -> timeline.py -> (scenes) -> render -> mix -> finish
- Audio only: mix.py -> finish.py (no video re-render needed)
```

### production-notes.md

Put it at the top level of the project folder. Write it so the next worker (or the next session) can remake everything as is.

- Concept summary (what was chosen, discarded candidates), structure table (time, segment, scene, narration, evidence source), where the critique records are
- Tools, models, voices, and settings used (voice_id, model, settings, music plan or synthesis spec)
- Photo source table, list of AI-generated images and where the prompts are (`assets/gen/.codex-imagegen-logs/`)
- Facts reflected differently from the request, items to check before publishing
- Regeneration commands (in the same order as "When fixing" above, with real paths)
- Files that must not be deleted: `audio/vo/` (regenerating costs credits), `audio/music/`, `assets/gen/`. Even when asked to clean up, keep these files, and report what was deleted and what was kept separately
