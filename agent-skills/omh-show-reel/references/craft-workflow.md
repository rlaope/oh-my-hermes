> Translated in full from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 `showreel/SKILL.md` (MIT, Copyright (c) 2026 Minho Hwang (revfactory); `toolkit/LICENSE.upstream`, provenance in `toolkit/upstream-manifest.json`). Read it for the upstream production method end to end: concept candidates, audio first, style frames, draft critique loops, finish and delivery report. `$S` is `toolkit/scripts` under the loaded skill directory. Commands here are upstream's; check the upstream command map in `toolkit/README.md` before running one. Content language follows `references/brief-and-locales.md`: Korean-first defaults apply only to Korean content, the craft bar applies to every locale; host install paths are placeholders here, upstream's default narration voice is named by role and chosen only through voice_policy, inline OMH notes mark where OMH policy overrides an upstream default, and the provider scripts are opt-in with the user's own key.

# Motion-graphics showreel production

> OMH overrides, which win over anything below: fonts are explicit local files, `new_project.py PROJECT --font /path/Face.ttf` (repeatable); there is no `--fonts` flag, nothing is prepared and nothing is downloaded from Google Fonts. The music default is `synth_music.py` or supplied, licensed audio, never a paid provider unless the user asks for it with their own key. Missing tools are reported with the install command for the user to run; this skill never runs it. Libraries come from the approved dependency root, not a download. Questions follow `references/brief-and-locales.md`. Commands below that differ from this kit's flags (`synth_music.py`, `qa_check.py --audio-mode`, `mix.py`, `timeline.py`) follow the upstream command map in `toolkit/README.md`.

A skill that makes Korean motion-graphics videos (resume showreels, promo videos, profile videos, teasers, brand films, event promos, product introductions, educational videos, making-of films) from concept to delivery. It does not pick a preset mood or template. For each request it drafts several concept candidates and picks the strongest, sets a fresh art direction for each segment, builds the screens in code (DOM, canvas, WebGL shaders, 3D), and then repeatedly looks at the rendered frames directly and rebuilds the weak segments. It carries the work through music, sound effects, ElevenLabs narration, codex-image images, the mix, and automated QA. It asks the user only for facts that only the user knows (the subject, information that must be included, where materials are), and makes creative decisions such as mood, length, structure, and whether to use narration on its own. For requests such as '쇼릴' (showreel), '모션그래픽' (motion graphics), '애니메이션 영상 만들어줘' (make me an animated video), '홍보 영상' (promo video), '소개 영상' (introduction video), '인물 소개 영상' (person introduction video), '1분 영상' (1-minute video), 'N초 영상' (N-second video), '이력서용 쇼릴' (showreel for a resume), '놀라운 모션 그래픽 디자이너' (amazing motion graphics designer), '전력을 다해요' (give it everything you have), '키네틱 타이포' (kinetic typography), '나레이션 넣은 영상' (video with narration), '티저 영상' (teaser video), and '하네스가 어떻게 동작하는지 영상으로' (a video showing how the harness works), use this skill even when the word "video" is not mentioned. Cut editing of live-action footage, work that only trims or converts files, calling generative video models such as Sora or Veo, and work that only produces slides or PDFs are out of scope.

## The bar this skill aims for

This skill started from the request below.

> 당신이 얼마나 놀라운 모션 그래픽 디자이너인지 보여주는 역동적인 한글버전 1분 모션그래픽 비디오를 만들어 보세요. 이력서용 쇼릴 처럼요. 전력을 다해요.
>
> (English: Make a dynamic, Korean-language, 1-minute motion-graphics video that shows how amazing a motion graphics designer you are. Like a showreel for a resume. Give it everything you have.)

What each part of the request demands of the output is as follows.

| Request | Meaning | What to check in the output |
| --- | --- | --- |
| 당신이 얼마나 놀라운 모션 그래픽 디자이너인지 (how amazing a motion graphics designer you are) | The video itself proves the maker's skill. How the screens were made shows before what they say | Every screen has judgment that a template would not produce (composition, motion design, material) |
| 놀라운 (amazing) | The viewer cannot predict the next screen | Screens made in a different way from the previous segment keep coming. Every segment has a "how did they make that" moment |
| 역동적인 (dynamic) | Not a video that is merely fast. Contrasts of fast and still, big and small change at the same moments as the music's beats and sections | There are both barrage segments and empty segments. There are no accidentally frozen segments; stillness exists only where it is intended |
| 한글버전 (Korean-language version) | Use Hangul as design material, not as translated subtitles | The forms of Hangul, such as jamo structure, strokes, the square block, and variable weight, are used in the motion |
| 이력서용 쇼릴 (showreel for a resume) | A format that strings together the best segments of different works to music and ends with a name (and contact details) | The range of expression is wide (2D, 3D, typography, data, photos, generative graphics, and so on). Each segment looks like a different project |
| 전력을 다해요 (give it everything you have) | Do not stop at the first idea; spare no time or iteration | There is a record of comparing several concept candidates and a record of rebuilding weak segments |

When this sentence comes attached to a different subject (a product introduction, an event promotion, a person profile), follow the request for the subject, and follow the table above for the standard of making. Even for requests without this sentence, the standards "놀라운 (amazing), 역동적인 (dynamic), 한글버전 (Korean-language version), 전력을 다해요 (give it everything you have)" apply as they are. The standard "each segment looks like a different project" applies when the format is a work compilation (showreel). For a video that must read as a single work, such as a brand or educational video, keep consistency inside the video first, and divide the scenes by medium and motion.

> OMH note: "한글버전 (Korean-language version)" is upstream's default because upstream makes Korean films. In OMH the content language comes from `references/brief-and-locales.md`; for Korean content this standard applies as written, and for any other locale read it as "use the content script's own forms as design material". The other three standards apply to every locale.

## What is not fixed in advance

Mood, palette, typeface pairing, scene structure, and whether to use narration are decided per request at the concept stage. The previous version of this skill set "dark background + gold accent + letterbox + film grain + HUD corners" as defaults, and as a result videos came out alike even with different subjects. Use such elements ("Predictable screens" in `references/craft-design.md`) deliberately, only when the concept demands them, and write the reason in `concept.md`.

Use the scripts, the engine, and the QA tools as they are. The tools do not decide what the screen looks like. They are for meeting technical quality such as sync, determinism, loudness, and flashes.

## Technical defaults

Items not in the request proceed with the values below.

| Item | Default |
| --- | --- |
| Length and format | 60 seconds, 16:9 1920x1080, 30fps. For Reels or Shorts, 9:16 1080x1920 |
| Narration | Include it only when the request asks for it or when the content must be told in words. A showreel communicates through music and screens. When you include it, pick a voice that fits the concept from the voice table in `references/craft-audio.md` and from `eleven.py voices --lang ko`. `ibCGc01503OQd2R6i1n1` (the verified Korean narrator) is a voice whose Korean reading settings (`eleven_multilingual_v2`, stability 0.45, similarity 0.8, style 0.4) have been verified |
| Music | Synthesized music from `synth_music.py`, or supplied licensed audio. ElevenLabs Music only when the user asks for it and has their own key |
| Images | Generate with codex-image only when the concept needs them. Do not generate the faces of real people; use only real photos |
| Deliverables | Master MP4, sharing MP4, poster JPG, subtitle SRT (when there is narration), production notes |
| Loudness | -14 LUFS. `mix.py` masters to a true peak of -2.0 dBTP, and the QA criterion is -1.0 dBTP or below |

> OMH note: the narration voice and language are not defaults in OMH. They come from the brief's voice_policy and content locale (`references/brief-and-locales.md`); the verified Korean narrator above is a candidate for Korean narration only. Narration and image generation use the opt-in `eleven.py`, `narrate.py` and `codex_ref_image.sh`, run only with the user's own key or signed-in codex; without them, use the music-and-picture version and code-drawn or supplied visuals.

## Where to work

Create every working file under the project folder. Save nothing in `/tmp`, `/private/tmp`, or the session scratchpad. When the session ends, temporary folders are deleted, and the regeneration commands, QA sheets, generated images, and narration takes can no longer be reused. Put QA stills and sheets in `<project>/qa/` and intermediate renders in `<project>/out/`.

If the user does not specify a project folder, create one under the current working folder with a lowercase English name (`./<topic-slug>/`).

## How the work proceeds

```
0 Environment check → 1 Read the request (ask only what is needed) → 2 Concept → 3 Research and materials → 4 Structure and script
→ 5 Audio first (music·SFX·narration → timeline) → 6 Images → 7 Style frames
→ 8 Scene production → 9 Draft render·critique loop → 10 Final render·mix·finishing → 11 Automated QA·delivery report
```

Ask questions only at stage 1, and only about facts that only the user knows. After that, do not ask; carry on through delivery. Problems that block progress (voice unavailable, music API unavailable, facts that cannot be verified) are handled through the fallback paths below and written in the delivery report.

Run long tasks (research, TTS, music generation, image generation, final render) with Bash `run_in_background` or a subagent, and move on to the next stage in the meantime. Do not wait with `sleep`. A video with many segments can be built concurrently by handing each segment to a subagent ("Splitting the build" in `references/craft-engine.md`).

Script paths are relative to this skill's folder (`<skill_dir>/toolkit/scripts/`). Below, this is abbreviated as `S=<skill_dir>/toolkit/scripts`.

## 0. Environment check

```bash
python3 $S/preflight.py
```

Reflect the "usable paths" in the output in the concept.

- **When the codex CLI or the image skills are missing**: the codex-image, photoreal, and codex-cli skills are at https://github.com/revfactory/skills . Guide the user through the printed install command. If they are not installed, build with code-drawn graphics and user-provided photos. The actual name of the skill that the user calls "realphoto" is `photoreal`.
- **When there is no ElevenLabs key**: if the request needs narration, guide the user through the key issuance steps that `preflight.py` prints, and tell them that work can proceed on a music-and-visuals version until the key arrives. Make the music through the synthesis path.
- **When the chosen voice is blocked** (the Free plan cannot use library voices): pick a usable voice with `python3 $S/eleven.py voices --lang ko`, or guide the user to upgrade the plan.

## 1. Reading the request

Follow "What to ask and what not to ask" in `references/craft-brief.md`.

- Ask: facts that are not in the request and cannot be found by research. Who or what the subject is, the must-include information for a real subject (name spelling, date and time, venue, URL, CTA), and where the user's materials are.
- Do not ask: mood, palette, length, aspect ratio, structure, whether to use narration, whether to use images. Claude decides these and writes them in the delivery report.
- When Claude itself is the subject, as in the core request above, ask nothing and start right away.

## 2. Concept

Read "Building the concept" in `references/craft-brief.md`. If the concept is weak, no amount of polishing in later stages will make the video distinguishable from a template video, so spend time on this stage.

- Write three or more candidates in different directions. For each candidate, write a one-sentence idea, the screen in the first 5 seconds, the segment structure, the way Hangul is used, and the technical problem this video has to newly solve.
- Compare the candidates against the same criteria and pick one: Is it memorable from the first 5 seconds alone? Can someone who has seen the previous segment not predict the next one? Is the range of expression wide? Would it fail to hold up without this subject? Is it distinguishable from a template video? Does it use the forms of Hangul as material? Can it be built with the engine and the remaining time?
- Write the chosen concept in `<project>/concept.md`. Decide the art direction (medium, palette, typeface, character of motion, texture) separately for each segment. How to decide it is in "Choosing the art direction" in `references/craft-design.md`.
- How to structure a showreel (work compilation, self-introduction) is in "Showreel" in `references/craft-story.md`.
- Once the concept is chosen, tell the user in a line or two and proceed without waiting for confirmation.

## 3. Research and materials

First create the project. The folder structure and the engine are prepared; fonts are the explicit `--font` files you pass, and renderer dependencies come from the approved dependency root.

```bash
python3 $S/new_project.py <project> --ratio 16:9 --duration 60 --font /path/to/Face.ttf
```

Add Hangul typefaces as explicit local font files with `--font` (it can be given more than once). No typeface is bundled or downloaded.

`reel/scenes.js` is created as an empty scene file. API usage examples are in `reel/_example_scenes.js`. Do not take the example's screens as a starting point; write anew from the concept.

When the subject is a person, company, event, or product, hand the research to a subagent in the background. The prompt is in "Research request prompt" in `references/craft-brief.md`.

- Leave the results in `research/research.md`. For each fact, write the source URL and the certainty (confirmed / single source / unconfirmed).
- Use only sourced numbers and facts in the video. When information the user gave differs from the research results, follow the research results and note it under "What was applied differently from the request" in the delivery report.
- Choose real photos from user-provided materials, official sites, and press photos, and write their sources in `research/photos.md`. Mark press photos in the delivery report as "permission to use must be confirmed before publication".
- Extract brand colors from the official site's CSS or from the logo. Use the official logo file only when the video is for that company, and do not draw other companies' logos.

## 4. Structure and script

Read `references/craft-story.md`. It has showreel structure, reference structures by purpose, reference values by length, copy rules, and pronunciation spelling rules.

- `storyboard.md`: a segment and scene table (time, on-screen copy, narration, screen design, transition, sound effects, source)
- `script.json`: narration lines, scene boundaries, sound effects, music. The format follows the description at the top of `narrate.py` and "Writing script.json" in `craft-story.md`.
  - Write segment and scene boundaries in `scenes`. Starts and ends can use bar cues (`bar9`) and hit cues (`music.hit2`).
  - Without narration, leave `"lines": []` and fill only `scenes`, `sfx`, and `music`. Skip `narrate.py` and start from `timeline.py`.
  - With narration, write the display text (`text`) and the pronunciation spelling (`tts`) separately, and name the words to align with scene transitions with `cues`. The amount must not exceed 255 characters for 60 seconds (by pronunciation spelling, excluding spaces). If it overflows, the screen cannot keep up with the narration.
- When a date appears, check the weekday against a calendar (`python3 -c "import datetime;print(datetime.date(2026,11,20).strftime('%A'))"`). If it does not match, drop the weekday and note it in the report.

## 5. Make the audio first

The screen timing is set by the music's beats and hits and by the narration's words, so lock the audio first. For a showreel, the music is the basis of the edit. Align the sections of the music spec with the segments in `concept.md`, and write the track's genre, instruments, and texture in `global_styles` to fit the concept. The detailed criteria are in `references/craft-audio.md`.

```bash
python3 $S/narrate.py <project>/script.json --stt            # when there is narration. Fix lines marked ✗ and run again
python3 $S/music_tools.py plan <project>/audio/music/spec.json # music spec → ElevenLabs composition plan
python3 $S/synth_music.py <project>/audio/music/spec.json --out <project>/audio/music/music.wav   # default, local
#   only when the user asked for ElevenLabs Music and has their own key: python3 $S/eleven.py music <project>/audio/music/music.mp3 --plan <project>/audio/music/plan.json
python3 $S/music_tools.py analyze <project>/audio/music/music.wav   # tempo and hits → align segment boundaries to the hits
python3 $S/eleven.py sfx-kit <project>/audio/sfx --names impact,riser   # only where a generic preset is needed (synthesized: `tick`/`boom`/`whoosh` events in the `synth_music.py` spec). For sounds that match a segment's material, eleven.py sfx "prompt"
python3 $S/timeline.py <project>/script.json --music-analysis audio/music/analysis.json
```

- Set music sections in 4-bar units (8 seconds at 120 BPM). ElevenLabs Music builds tracks in that unit, so if the drop comes later than the time you want, use `music_tools.py splice` to splice the drop section in a few beats after the end of the build-up and pull it earlier.
- Design the sound effects to match each movement on screen. Do not just pick preset names; use `eleven.py sfx "prompt"` to make sounds that match the segment's material (paper, glass, liquid, electronic).

`timeline.py` creates `timeline.json` (for the mixer and QA) and `reel/timeline.js` (the cues, word times, and loudness curve for the screen). It reports overlaps, length overruns, and missing cues with ✗, so fix them all before building the scenes. When changing narration wording or timing, edit only `script.json` and run `narrate.py` (which regenerates only the changed lines) and `timeline.py` again.

## 6. Images

Do this only when the concept needs photos or generated images. Read `references/craft-images.md`.

- Generation: `<codex-image skill>/scripts/codex_imagegen_batch.sh <project>/assets/gen "prompt::name.png" …` (5 at a time in parallel, about 1 minute per image)
- Photo-style images with people in them: build the prompt with the `photoreal` skill.
- To make an image resemble a real subject: attach a reference photo with `$S/codex_ref_image.sh`.
- Post-processing: `python3 $S/prep_images.py <project>/assets/gen --out <project>/assets/img [--cutout]`. It removes letterboxes, upscales, and cuts out the background.
- Check: make a sheet with `python3 $S/prep_images.py --sheet <project>/assets/img --out <project>/qa/sheet_images.png` and look at it with Read. Regenerate images with mangled fingers, text, or logos.

## 7. Style frames

Before writing the full scenes, make 1-2 representative frames per segment and look at them as one sheet.

- Check whether each frame is good enough to use as a poster, whether the segments look like different works from one another, and whether any element from "Predictable screens" in `craft-design.md` is there without a reason.
- Change the direction at this stage for segments that fall short. For a segment where two or more directions come to mind, make both and compare. This costs less than changing direction after all the scenes are built.

## 8. Scene production

Read `references/craft-engine.md` (engine API, how to write scenes, WebGL and 3D, splitting the build) and `references/craft-design.md` (art direction, motion principles, rhythm, Hangul typography), then write the scenes. `references/craft-techniques.md` holds 22 verified technique codes. If the expression the concept demands is there, take the code; if it is not, build it new. Do not plan scenes by picking from the list.

- Engine rule: the screen is a pure function of the time t. Do not write code that relies on `Math.random`, `Date.now`, CSS transitions or animations, or the state of the previous frame. The renderer jumps to arbitrary times, and several workers split the drawing between them. Calculations that need accumulation, such as physics simulations, are precomputed at fixed intervals in setup and read by time in render.
- There is no limit on the means of expression. DOM and SVG, canvas 2D, WebGL2 shaders, and three.js 3D all render ("WebGL: shaders and 3D" in `craft-engine.md`).
- Do not write times as literal numbers; use timeline cues with `REEL.cue('name')`. That way the screen follows when the audio is regenerated.
- Place hard cuts and state changes 0.5 frames before the cue (`cue(x) - 0.5/fps`). The motion-blur shutter straddles each frame, so this is what makes the new state show exactly on the cue frame. Scene boundaries work the same way: `REEL.scene({ start: cue('scene.s02') - 0.5 / REEL.fps, end: cue('scene.s02.end') - 0.5 / REEL.fps, … })`. If you use integer-second cues as they are, the segments before and after mix on the boundary frame in a `--sub 4` render.
- The concept decides how the first frame starts. If it starts with a blank screen, silence, or a fade, write the intent in `concept.md`. Do not start with an unintended blank frame.
- Colors follow the per-segment art direction in `concept.md`. When a real brand is the subject, use the official colors (site CSS, logo). The color tokens in `reel/index.html` are gray placeholder values, so do not leave them as they are.
- A video over 3 minutes or a showreel with many segments can be split into `scenes_sNN.js` per segment and handed out to subagents ("Splitting the build" in `craft-engine.md`).

## 9. Draft renders and critique loop

```bash
node $S/render.mjs --dir <project>/reel --stills <start+0.5>,<cue+0.4>,<end-0.6> --outdir <project>/qa/stills_<scene>   # every time you build a scene
node $S/render.mjs --dir <project>/reel --every 0.5 --outdir <project>/qa/stills     # full stills (after every scene exists)
python3 $S/contact_sheet.py --dir <project>/qa/stills --out <project>/qa/sheet_stills.png --timeline <project>/timeline.json
node $S/render.mjs --dir <project>/reel --out <project>/out/draft.mp4 --scale 0.5          # draft (about 30 seconds for 60 seconds of video)
python3 $S/contact_sheet.py --video <project>/out/draft.mp4 --every 1 --out <project>/qa/sheet_draft.png
python3 $S/motion_check.py <project>/out/draft.mp4 --timeline <project>/timeline.json   # reports accidentally frozen stretches, lack of large motion, and excessive flashes with times and scene names
python3 $S/contact_sheet.py --video <project>/out/draft.mp4 --around <segment boundary seconds> --frames 3 --out <project>/qa/sheet_cuts.png
```

**Always open the sheets you made with Read and look at them yourself.** Do not call the work done without looking at the rendered frames.

For each draft, follow "Critique" in `references/craft-qa.md` to judge each segment as keep, fix, or rebuild, and record it in `qa/critique_NN.md`. Rebuild the weakest segment by changing its direction rather than by tweaking values. Do not fix once and stop. Repeat until every segment is "keep" and the technical checklist in `craft-qa.md` passes. Before the final render, at least once, give a subagent that has no context of the making only the sheets, the frame strips, and the critique questions, get its verdict, and record it in `qa/critique_NN.md`. This is to find the problems the maker missed.

When `motion_check.py` reports △, check whether that time is an intended pause, and if it is not, add an event. Fix a flash ✗ at the draft stage regardless of intent (photosensitivity). Fixing it after the final render means rendering again. Even if a draft (without motion blur) passes, in the final render (`--sub 4`) cuts blend across two frames and flashes can increase. For a segment with frequent cuts on a light background, before the final render, extract just that segment with `render.mjs --from <sec> --to <sec> --sub 4 --scale 0.5 --out <project>/out/chk_<segment>.mp4` and check it with `motion_check.py`. If the renderer exits with code 2, a page error occurred, so fix the errors in the log first.

## 10. Final render, mix, and finishing

```bash
node $S/render.mjs --dir <project>/reel --out <project>/out/video.mp4 --sub 4 --format png   # motion blur. About 3-5 minutes for 60 seconds of video; run it in the background
python3 $S/mix.py <project>/timeline.json
python3 $S/finish.py --video <project>/out/video.mp4 --audio <project>/audio/mix.wav \
  --name "<title>_<length>s" --outdir <project>/out --timeline <project>/timeline.json
```

Do not put reverb on the narration. A video that used a 2.4-second hall at `--hall 0.12` drew the comment "there is too much echo on the narration". Use `--hall 0.04~0.08` only when a sense of space is truly needed, and check that the "tail reverb at line ends" that `mix.py` prints is ✓ (-32dB or below).

`mix.py` shows the "narration vs. background" dB for each line. For a line marked ✗ (under 6dB), lower the nearby sound effects or move them 0.2-0.3 seconds off the key word, and mix again. When fixing only the audio, do not render the video again; run only `mix.py` and `finish.py` again.

## 11. Automated QA and delivery report

```bash
python3 $S/qa_check.py <project>/out/<name>.mp4 --audio-mode <muted|music-only|narration|narration+bed/SFX> --policy <project>/qa-policy.json   # the mode of this film; no --timeline/--script/--stt
```

In this kit it checks the format, loudness, overly dark stretches, flashes and frozen screens and prints a JSON report; it does not transcribe the finished mix and does not write `qa/qa_report.md` or a final sheet (use `contact_sheet.py` for the sheet). A finished-mix transcript check is not observed unless you ran separate approved speech-to-text tooling. Handle every "to fix" item, look at the final sheet with Read, and then deliver. For a line that STT got wrong only once, run it once more, and fix it if it is wrong both times.

The formats of the delivery report and `제작노트.md` (production notes) are in "Delivery" in `references/craft-qa.md`. Always include the following.

- A **table of absolute paths** of the deliverables
- The segment structure table, the chosen concept, and the discarded candidates
- What Claude decided (mood, length, whether to use narration, and so on) and what was applied differently from the request
- What to check before publication: permission to use photos, single-source facts, information that becomes wrong after a point in time, and the fact that AI-generated people are fictional
- The regeneration commands
- A request that the user listen to the sound themselves. Claude cannot hear sound and checked it only by the numbers.

## Rules to keep

- Do not generate images of the faces or bodies of real people. Use generated images for environment, object, or from-behind shots where no face is visible.
- Do not imitate the logos or brands of real companies. Create new names and marks for the brands in fictional commission segments.
- Use only numbers, job titles, and years in the video that have a research source. If you use fictional figures for staging, say so on screen or in the report.
- Do not put artist, composer, or song names in music prompts. They trip the copyright filter and are rejected with a 400.
- Save ElevenLabs credits. Regenerate only the changed lines, and use `takes` only on lines with proper nouns or numbers.
- Use flashes at opacity 0.15 or less on a dark background, and no more than 3 per second (photosensitivity).

## Common problems

| Symptom | Action |
| --- | --- |
| Segments look alike | Check that neighboring segments differ in at least two of medium, palette, typeface, motion, and texture. If they do not, redo the art direction of the weaker segment |
| The video looks frozen or flat | Check whether the times `motion_check.py` reported are intended pauses. If they are not, add new events (an entrance, a rearrangement, a camera move), move the foreground and background at different speeds, and turn exits into motion that carries into the next composition |
| Narration runs past the target length | Cut the script (60 seconds = 255 characters or fewer, fewer when there are many short lines). If it still overflows, raise speed only up to 1.05 |
| Names or numbers misread (이훈희 -> 이후니, 2026 -> 2025) | Fix the pronunciation spelling -> break it with commas ("이공, 이육") -> `takes` 3-5 -> replace only that line with model `eleven_v3` |
| Too much echo or reverberation on the narration | Run only `mix.py` and `finish.py` again, without `--hall` (no video re-render needed). When keeping reverb, lower `--hall` until the "tail reverb at line ends" in `mix.py` is ✓ |
| Speech gets buried in the finished mix | Move impacts 0.2-0.3 seconds off key words, raise that line's `gain_db` by +2 to 3, `--duck` 0.8 |
| An error JSON gets saved as an mp3 | `eleven.py` prevents this. Do not use curl directly; use the script |
| SSL error when calling ElevenLabs from Python | Do not turn off verification. `eleven.py` uses curl, so it does not have this problem |
| The on-screen font comes out as the default gothic (sans-serif) | Check the "font" line in the render log, and check whether `reel/fonts/fonts.css` has that weight |
| A WebGL screen comes out black | Check that the context was created with `preserveDrawingBuffer: true` and that the drawing happens inside render. Keep libraries as files in `reel/lib/` and load them from there |
| Blank screen or ghosting at a scene boundary | Look at ±3 frames with `contact_sheet.py --around` and finish exits 0.1 seconds before the cut |
| The music differs from the plan's section lengths | This is normal (it is usually generated in 4-bar units). Read the hits with `music_tools.py analyze` and align the segment boundaries to the hits, or move the drop to the time you want with `splice` |
| In a vertical (9:16) video, the HUD or subtitles are covered by the app UI | For vertical videos, `fx.js` automatically avoids the top 250px and the bottom 420px. Keep elements you draw yourself out of these areas too |
| The video comes out as yuvj420p, full range | Going through `render.mjs` and `finish.py` produces yuv420p, tv range. Do not encode with other tools |

## References

| File | When to read it |
| --- | --- |
| `references/craft-brief.md` | Stages 1 and 2: what to ask and what not to ask, building the concept and the `concept.md` template, time and credit estimates, research and photo-collection prompts |
| `references/craft-story.md` | Stage 4: showreel structure, reference structures by purpose, reference values by length, copy and pronunciation spelling rules, script templates |
| `references/craft-audio.md` | Stages 5 and 10: voices, models, and settings, ElevenLabs key and plan, music and sound effects, mix criteria |
| `references/craft-images.md` | Stage 6: image generation, photorealistic photos, cutouts, post-processing |
| `references/craft-design.md` | Stages 2, 7, and 8: choosing the art direction, predictable screens, motion principles, rhythm, Hangul typography, safe areas, transitions |
| `references/craft-engine.md` | Stage 8: engine API, how to write scenes, WebGL and 3D, splitting the build |
| `references/craft-techniques.md` | Stage 8: 22 verified technique codes and the rules for sync, the first frame, flashes, and determinism |
| `references/craft-qa.md` | Stages 9 and 11: critique, technical checklist, how to read sheets, delivery report and production notes templates |
