# Design: art direction, motion, Hangul typography

## Contents

- Choosing the art direction
- Predictable screens
- Motion principles
- Rhythm
- Hangul typography
- Layout and safe areas
- Transitions
- Flash safety
- Short promo clips
- What not to do

## Choosing the art direction

For each segment in `concept.md`, decide the five things below. For a showreel, each segment should come out with a different answer. Repeating the same background color and typeface inside one video makes it look like a single piece of work stretched out. Inside a segment, keep the chosen values consistent.

| What to decide | How to choose |
| --- | --- |
| Medium | DOM typography, SVG lines, canvas 2D (particles, procedural drawing), WebGL (shaders, 3D), photos and generated images, or a combination of these. Changing the medium per segment makes the range of expression visible at once |
| Palette | Draw it from the subject: official brand colors, the colors of the photos, the industry and era of the fictional commission. Light backgrounds, primary-color contrast, monochrome, and black-and-white are candidates too. Choose a dark background when there is a reason |
| Typeface | Beyond the typefaces `new_project.py` prepares (Pretendard variable 45-920, Noto Serif KR, Black Han Sans, Anton, JetBrains Mono, and Paperlogy and 에이투지체 (A2Z) if they are available locally), add Google Fonts typefaces (all OFL) with `new_project.py <project> --fonts "Hahmlet:wght@300;900" --fonts "Gowun Batang:wght@700"`. List weights separated by `;`, not as a range. Check in the font list of the render log that they were actually loaded |
| Character of motion | Weight (does it bounce lightly, or drop heavily), material (paper, liquid, metal, light, cloth), speed distribution (mostly fast with one slow moment, or the reverse). These answers decide the easing and timing |
| Texture | Flat, halftone, dither, pixel, glass, ink bleed, film grain, and so on. Do not lay one texture over every segment |

When a real brand is the subject, take the palette and typeface from official materials, and divide the segments by medium and motion.

## Predictable screens

The elements below were this skill's earlier defaults, and in evaluation runs they appeared both in videos made with the skill and in videos made without it. They are why videos looked alike even with different subjects.

- Dark background + a single accent color (gold, cyan, orange) + vignette + film grain
- Corner brackets, timecode, `CH.01 / TITLE` chapter labels, a bottom progress bar
- Small uppercase English monospace labels placed on every screen
- The same slam on every big hit (a 1.3-2x scale-up, landing out of blur) + screen shake + flash
- A structure in which a centered title + subhead card is swapped one after another
- Perspective grid floors and floating dust laid down to fill an empty background
- An opening that starts with terminal typing + a blinking cursor
- An opening in which a letterbox opens, lens flares
- A slow push-in at the same rate on every scene

These elements are not forbidden. If the concept demands one, use it deliberately and write the reason in `concept.md`. If one is there without a reason, remove it. Check the screens against this list at the style frame and critique stages.

## Motion principles

The quality of motion does not show in still frames. Pull the key moments as frame strips at intervals of 0.1 seconds or less, and look at how the amount of movement changes from frame to frame ("Critique" in `craft-qa.md`).

| Principle | What it does |
| --- | --- |
| Anticipation | Before a big move, pull back slightly in the opposite direction for 3-6 frames. Place the anticipation before the cue so the result is visible on the cue frame |
| Overshoot and settle | When stopping, pass the target and come back (`ease.outBack`, `spring`). Heavy things overshoot less; light things bounce several times |
| Overlapping action | The parts of one mass (syllables, jamo, strokes, pieces) do not depart and arrive on the same frame. Stagger the departures by 2-4 frames |
| Follow-through | After the main action ends, the attached elements (shadows, afterimages, dangling lines, particles) stop later |
| Secondary action | Draw the results the main action produces. When a letter drops, the floor gets pressed; when a stroke is drawn, the ink bleeds |
| Spacing | Even over the same distance, how the amount of movement changes per frame decides the character. Do not move every element with one default easing. Define a curve per element with `kf`, `spring`, or a function you write yourself |
| Eye trace | The first move of the next composition starts where the move of the previous composition ends. Put the subject of the next screen where the eye was just before the cut |
| Depth | Move the foreground, midground, and background at different speeds. Separate the layers so that perspective appears when the camera moves |
| Physics | Compute falls, damped oscillation, and air resistance in closed form (`craft-techniques.md` T04, T14). Precompute simulations that need accumulation in setup (`craft-engine.md`) |

The starting values are below. Change them when the art direction demands it.

| Item | Starting value |
| --- | --- |
| Entrance | 0.35-0.7 seconds; large movement, short time. Slow, small movements look like slides |
| Exit | 0.25-0.4 seconds. Finish 0.1 seconds before the cut |
| Multiple elements | Stagger at 0.03-0.08 second intervals |
| Shake | Amplitude 12-18px, decay 0.4 seconds. Only for big events |
| Numbers | Count up over 1.2-1.8 seconds, outQuart. Do not roll small values; stamp them in at once (the intermediate values read as real values) |
| Cue sync | Key events are visible within ±3 frames of the cue |
| Last frames | Do not put new information in the last 10 frames |

## Rhythm

- Leave no accidentally frozen screen. Keep stretches in which nothing changes for more than 1 second only as intended pauses (a music stop, a breath, the end card). `motion_check.py` reports such stretches with their times. The thresholds (frozen-screen ratio, large-motion p90) are 8% and 15 for 20 seconds or shorter, 20% and 7 for 60 seconds or shorter, and 35% and 6 for longer videos.
- When one composition lasts longer than 2 bars (4 seconds at 120 BPM), check what changes inside it, and if it is not an intended pause, change the composition or add a new event (an entrance, a rearrangement, a camera move).
- Put contrast into the size and spacing of events. Decide the barrage sections and the empty sections to match the structure of the music, and empty out or scale down before a big event. Putting events of the same size on every beat flattens the rhythm.
- An exit is motion too. Do not just lower the opacity: push into the next composition, transform, or become an element of the next composition. `REEL.inout` is one way to do it.
- Values to use when making the screen react to sound: `REEL.level` (loudness curve), `REEL.pulse` (hits), `REEL.TL.music.beats`.
- A screen with only text on a black background looks frozen even with a zoom added. Create background motion that fits that segment's art direction.

## Hangul typography

### Using Hangul as material

Hangul is a structure in which jamo are assembled inside a square block, so it allows movements that Latin letters cannot. Below are methods that have been tried in the engine.

- Jamo decomposition and assembly: cut a syllable into its initial, medial, and final regions and move them separately (`craft-techniques.md` T05). Computing the syllable codes lets you show the typing process, as in ㅎ -> 하 -> 한.
- Stroke drawing: extract the typeface outlines with fontTools, turn them into SVG paths, and draw them with `stroke-dashoffset` (the "precise method" in T05).
- Variable weight: change the `wght` of Pretendard Variable per letter in time with the beat (T06).
- Square grid: put syllables into cells and flip and rotate them like tiles (T10).
- Particles and 3D: sample letters from pixels into dots (T04), or use letters drawn on a canvas as a WebGL texture (`craft-engine.md`).
- Vertical writing (`writing-mode: vertical-rl`), dropping only the final consonants (batchim), swapping the same syllable through several typefaces.

### Sizes and rules

| Use | Size (at 1080p) | Rules |
| --- | --- | --- |
| Display headline | 120-260px | At weight 900, letter spacing -0.03 to -0.05em, line height 1.05, two lines or fewer |
| Words and names of 1-3 characters | 300-480px | May fill the whole screen |
| Giant numbers | 200-400px | `tabular-nums`; set the units small in the body typeface |
| Body and explanation | 40-64px | Around 20 characters per screen |
| Subtitles | 38-44px | 64-104px from the bottom, two layers of shadow |
| Minimum size | 32px for text that must be read, 48px for subheads and CTA | Do not make the end card CTA the smallest text |

- Use `word-break: keep-all` (it is in the template). If a line breaks in the middle of a word unit (eojeol), or only a particle drops to the next line, break the line by hand (`<br>`).
- English display typefaces (Anton, JetBrains Mono) have no Hangul. Put a Hangul typeface at the end of the font stack. The template variables (`--num`, `--mono`) already include one.
- For mask reveals, use `split(el, 'char', {mask: true})`. The mask padding (.12em/.18em) is needed so final consonants and upper dots are not clipped.
- Giving `text-shadow` to letters inside a mask leaves rectangular ghosting. Draw a glow separately as a blurred duplicate layer of the same letters.
- Gradient text (`background-clip: text`) disappears on child spans that carry a transform. Apply the gradient per letter and chain the `background-position` values.

## Layout and safe areas

16:9 (1920x1080):

- Body safe area x 120-1800, y 120-900
- Elements that hug the screen edge sit 46px inside
- Subtitle area y 940-1040. In a video with subtitles, do not bring graphics below y 900
- Keep the subtitle area clear even in scenes where the camera moves. There was a case where the overlap showed up only in the finished MP4

9:16 (1080x1920):

- Leave the top 250px (the app's top UI) and the bottom 420px (captions, buttons) empty (burned-in subtitles sit in the bottom 440px)
- Headlines within 80% of the screen width, 6-8 characters per line
- Zoom into landscape photos with a virtual camera and follow the subject (scale around 2)

An intentional crop (giant text overflowing the screen) is an exception to the safe-area rules.

## Transitions

A transition is the logic that joins two segments. Design it so that the next segment inherits one of the previous segment's shape, color, or direction of motion. Do not use the same transition three times in a row.

| Transition | Method | Where it fits |
| --- | --- | --- |
| Match cut | A shape from the previous scene (dot, circle, line, letter) becomes a different element of the next scene at the same position and size (T16) | Joining dissimilar segments |
| Shape morph | The previous element transforms into the first element of the next segment (particle re-forming T04, number-to-letter morphing T03) | Where the medium changes |
| Zoom-through | Scale up one point in the screen (the hole in a letter, a screen, a pupil) 7-9x with inExpo | Going inside a segment |
| Mask reveal | `clip-path: inset()` or `circle()` opens | Photos and cards entering |
| Color-field wipe | A field of color comes in and leaves out the other side (0.2+0.3 seconds) | Between two segments of different colors |
| Slats | Vertical bars open in sequence, and once all are open, swap to a single image to remove the seams | Photo montages |
| Whip pan | 4 frames of movement on the incoming side + horizontal blur (T18) | Movement that continues in the same direction |
| Push | The next scene pushes in while the previous scene moves -35% | Lists and sequences |
| Stop + blackout | 0.5-1 second of blank screen together with a music stop | Turning points and twists |
| Pull back | The camera pulls back and the whole structure is revealed | Closing a system explainer, gathering a whole segment into one view |

## Flash safety

Keep changes in which 10% or more of the screen rises and falls by more than 0.1 in brightness to 3 or fewer per second (photosensitivity). Flashes on a dark background use opacity 0.15 or less, for 0.12-0.25 seconds. The detailed rules are in "Common rules" and T20 in `craft-techniques.md`.

## Short promo clips

> OMH note: upstream designs multi-segment showreels. A promo or social clip of 15 seconds or less is a single segment, and the rules below override this file's per-segment variety, transitions, giant numbers, and end card for it. They generalize reviewer feedback on repeated revisions of short launch clips.

- Hold one hero scene from the first frame to the last. No scene cuts, no end-card lockup; vary the shot with the camera (push, tilt, parallax), light (a slow drift, one or two sweeps), and speed (trails, streaming type).
- No meta text: explanatory labels ("REAL STREAM", "NOT SPED UP"), subheads, model or product IDs, URLs, footnotes. Viewers read the meaning from the picture and have no time to read a short clip; text only crowds it. Links, prices, and IDs go in the post that carries the clip.
- One number. The single key figure sits on one line under the logo or subject, smaller than it (about 0.35-0.45 of the logo height). No giant extruded number scene and no second or third figure (a discount, a multiplier, a footnote, a live counter whose value differs from the headline).
- The official logo as supplied, unboxed and large: at least 25% of the frame height in the opening. A small icon beside a text label does not replace it. Never redraw or regenerate a logo; on a dark ground only its color may change.
- No slop UI: glass cards, pill badges, "LIVE" badges, rounded stat boxes, invented terminal or dashboard UI, default-font white text on black. A real product capture follows the full method instead.
- Smooth light: gradients interpolate in oklab/oklch over several stops across broad radial or mesh fields with 1-3% noise dither against banding, no hard edges or rainbows. Shade the subject with a local light (rim light, soft glow), a vignette, and soft layered shadows instead of a full-screen glow or flash.
- An OFL typeface pairing chosen for the clip (the brand's own face first), bundled with its license; never the system UI face or Inter by default.
- Before rendering the video, render a still sheet (first frame, number entrance, middle, last frame), view it yourself, and check every item above. A failed item is a revision before the full render, not a note after it.

## What not to do

- Title + bullet-list screens (they look like slides), and putting more text on one screen than the reading time allows (6-8 Hangul characters per second)
- Adjective copy without numbers or facts ("혁신적인" (innovative), "획기적인" (groundbreaking))
- Drawing other companies' logos or compositing the faces of real people
- Emoji (draw icons as SVG)
- Stacking several blur filters over the whole screen (rendering becomes several times slower)
