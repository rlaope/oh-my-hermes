# Idea-video genres

Recipes for the idea lane (`## Idea Videos` in the skill body): a video authored
from a text idea, with no product claim, real UI or brand asset on screen. Each
recipe is a starting concept, not a fixed style; anything the user asked for
wins over it.

Conceptual source: the community collection yihui-dev/awesome-opus5-5-videos at
`92aee2f586ac0715cb3cbcb6384834f98a33383d` (MIT), 703 short videos a model
authored as HTML from a prompt. Only aggregate counts are used here; no prompt
from the collection is copied. Its four categories: motion 369, 3D 117,
explainer 116, interactive 101. Its renderer tags: canvas 267, SVG 183, three.js
131, shader 92, GSAP 86, CSS 57, audio 39. The median prompt was 221 characters.

## What a short brief needs

A short ask rendered well when the brief fixed five things. Fill each one from
the user's words first and from the defaults second, and label every default:

1. a concrete subject: a named mechanism or object, not "something cool";
2. a duration: 20-30 s when none is given, about 2.5 s per beat;
3. one style anchor: a palette family, a material or a reference look;
4. one self-contained HTML file with its time controlled by a seek;
5. a verification pass: style frames, a draft, a contact sheet, one rebuild.

## Recipes

| Genre | Concept default | Medium default | Beats in 25 s |
| --- | --- | --- | --- |
| Concept explainer (how X works, a recipe, a history) | one object transformed step by step, a caption per step | SVG or canvas, GSAP timeline | 8-10 |
| Motion graphics and kinetic type | type and shape moving on one camera path | SVG and CSS transforms, GSAP | 8-12 |
| 3D scene | one lit scene, one slow continuous camera move | three.js, a fixed seed for any noise | 4-6 |
| Data-viz animation | one chart that builds, then one highlighted change | SVG or canvas; values copied from the named source | 5-7 |
| Logo or title intro | the mark assembled from its own shapes, held at the end | SVG, 5-10 s total | 3-4 |
| Music visual | shapes driven by beat times measured before authoring | canvas or shader; the audio file the user supplied | one per bar |

A short or vertical cut of any of these is 1080x1920 and keeps the 9:16 safe
areas in `references/craft-design.md` (Layout and safe areas) clear.

- An explainer shows the mechanism, not a wall of text: at most one line on
  screen at a time, at least 2% of the frame's shorter side tall.
- A data-viz animation shows only numbers the user supplied or a named source
  gave. A number with no source is HOLD.
- A music visual needs the audio before the beats; with none, ask once or make
  it muted with a visible pulse and say so.
- A 3D scene renders slowly; render the style frames at half scale first.

## Renderer probe, in order

Run read-only checks first and install nothing.

1. HyperFrames, when `command -v hyperframes` finds the CLI (the npm package
   `hyperframes`, documented by Hermes' optional `hyperframes` skill): author
   the composition its way (`data-*` timing, `gsap.timeline({ paused: true })`),
   then `hyperframes lint` and `hyperframes render --output <name>.mp4 --fps 30`.
   Do not run `npx hyperframes` when the CLI is absent: `npx` downloads it.
2. The show-reel toolkit: `python toolkit/scripts/preflight.py` with an explicit
   Chrome or chrome-headless-shell, an explicit `puppeteer-core` dependency root
   and FFmpeg/FFprobe, then `node toolkit/scripts/render.mjs` as
   `toolkit/README.md` gives it. The engine and its paused timeline are in
   `references/craft-engine.md`.
3. A frame renderer already installed, such as Python with Pillow drawing each
   frame from a pure function of time and piping it to FFmpeg. Keep the same
   determinism: no wall clock, a fixed seed for any noise.
4. None runs: HOLD. Name what is missing and the exact command that would
   install it (for example `brew install ffmpeg`, or
   `npm install -g hyperframes`), ask once whether to run it, and keep the
   composition and storyboard as the useful partial result.

## Measured delivery

`ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate:format=duration,size -of json <file>`
gives the export facts; add `shasum -a 256 <file>`. Report the path, codec,
dimensions, fps, duration, size and digest as measured. Generated is not
attached, sent or published.

## Hand-offs

- A product, launch, brand or work film, or any product fact or real UI on
  screen: the full show-reel method.
- A math proof, equation or algorithm animation: Hermes' `manim-video` skill
  when the host has it.
- Existing footage converted to ASCII art: Hermes' `ascii-video` skill.
- Summarizing, transcribing, captioning or trimming a recording that exists:
  `media-input-operator`.
- An animation inside an app's own UI (a button, modal, page transition or
  loading state): `frontend`.
