# Images: Generation, Real Photos, Cutouts, Post-processing

Script paths on this page use `S=<skill_dir>/toolkit/scripts`, where `<skill_dir>` is this skill's folder.

## Contents

- Deciding which images to use
- Generating with codex-image
- Photo-style images with people (photoreal)
- Making it look like a real subject (reference images)
- Using real photos
- Post-processing and checks
- How images go into the video

## Deciding which images to use

| Situation | Images to use |
| --- | --- |
| Introducing a real person | Real photos only (user-supplied, official, press). Mood shots (stage, office, city at night) are generated without faces |
| Companies and products | Official logos and product screens + UI mockups drawn in code. Generated images only as background texture |
| Events | Generated people as backs, silhouettes, crowds. For speakers, only text with their real name and affiliation |
| Research and data | Diagrams drawn in code (canvas, SVG). Notice: "an illustration drawn for explanation" |
| Pets and products | Attach a real photo as a reference and generate the same subject in a new scene (`codex_ref_image.sh`) |
| Without images | Build it from typography, shapes, particles, and data visualization only |

Do not generate the faces of real people. It can lead to impersonation or misunderstanding. Even if the user says "make a portrait with realphoto (photoreal)", if the person is real, tell them that you will use real photos and use generation only for fictional people and views from behind.

## Generating with codex-image

> OMH note: every codex image run, `codex_imagegen_batch.sh` and `codex_ref_image.sh` alike, draws on the user's own ChatGPT plan. Run it only after `omh-spend-gate`'s card, which names how many images and the plan they draw on, and the person's typed yes to that card.

```bash
<codex-image skill>/scripts/codex_imagegen_batch.sh <project>/assets/gen \
  "<prompt>::01_stage.png" "<prompt>::02_city.png" ...
```

- It runs 5 images at a time in parallel and takes about 1 minute per image. Run it with Bash `run_in_background` and do other work in the meantime. The number of concurrent generations is fixed at 5 in the script, so if you need to lower it (when sharing usage with other work), pass fewer items at a time.
- Results land in `assets/gen/`, logs in `assets/gen/.codex-imagegen-logs/`.
- Rerun only the ones that failed ("model is at capacity"). Take the files that already exist out of the list before running.
- The resolution is about 1.57MP (16:9 is 1672x941, 3:2 is 1536x1024). For video, upscale to 2400px with `prep_images.py`.

### Prompt template

Attach the same **common tail** to the shots of one section to keep the tone consistent. For the light, palette, and texture wording in the tail, write out that section's art direction from `concept.md` in English.

```
<scene description: place, subject, composition, light>. <the light, palette, texture of the concept.md section, in English>, wide 16:9 landscape frame,
large empty negative space on the left for typography, absolutely no text, no letters, no logos, no watermark
```

- State the aspect ratio in words, such as "wide 16:9 landscape frame". If you write a ratio and a resolution that disagree, such as "16:9 (1536x1024)", the model paints black bars at the top and bottom (`prep_images.py` crops them off, but resolution is lost).
- Specify where the text will go (negative space). Place people and objects in one third of the frame.
- Keep on-screen monitors and signs free of text, e.g. "blank glowing screens with abstract color only". Hangul lettering almost always comes out mangled.
- Write people as "seen only from behind as silhouettes, no faces visible".
- You can leave a space empty in the image for compositing graphics: "the screen is pure deep black, reserved for compositing graphics later"

Example (actually used):

```
Cinematic photoreal still of a television broadcast master control room at night during a live show. A long wall of dozens of
glowing monitors showing blurred colorful stage images, a wide mixing console with hundreds of small illuminated buttons in the
foreground, two crew members seen only from behind as dark silhouettes with headsets, faces not visible. Only practical light from
the screens and console, deep shadows, slight haze, subtle film grain, slightly off-center framing. No readable text, no logos, no letters anywhere.
```

## Photo-style images with people (photoreal)

For photoreal shots that feature fictional people, read the `photoreal` skill first and then build the prompt. It collects instructions for avoiding slick, ad-photo-shoot results and making the image look like a smartphone snapshot.

```bash
python3 <photoreal skill>/scripts/build_prompt.py --subject "30대 한국인 엔지니어 세 명" --scene office \
  --n 3 --level standard --lang en --emit-batch <project>/assets/gen
```

- Writing camera specs (85mm, f/1.4) pushes the result toward a photo-shoot look.
- "nobody looking at the camera", "framing tilted a degree or two", and "phone camera noise" were effective for naturalness.
- After generating, check the number of fingers, the pupils, stray lettering, and age.

## Making it look like a real subject (reference images)

> OMH note: every codex image run, `codex_imagegen_batch.sh` and `codex_ref_image.sh` alike, draws on the user's own ChatGPT plan. Run it only after `omh-spend-gate`'s card, which names how many images and the plan they draw on, and the person's typed yes to that card.

The codex-image batch script does not accept reference images. When putting a real subject such as a pet, a product, or a character into a new scene, use this script.

```bash
sips -Z 1024 photo.jpg --out <project>/assets/refs/ref1.jpg      # references at 1024px on the long side
bash $S/codex_ref_image.sh <project>/assets/gen/g01.png \
  "<identity features restated in words> + <scene> + 가로 16:9 구도, 글자·로고 없음" <project>/assets/refs/ref1.jpg
```

- Consistency held only when the identity features (coat pattern, eye color, collar, product color and shape) were restated in words.
- Test one image first, then run the rest in the background, at most 5 at a time. Files already made are skipped.

## Using real photos

- Record the sources as a table in `research/photos.md`: filename, original URL, article URL, resolution, content, quality.
- Open each photo you receive with Read and confirm it is the right person. Filter out people with the same name.
- Mark photos where a signature or official seal is visible, such as press photos, letters of appointment, and nameplates, as "check before publishing" in the delivery report.
- Use low-resolution article photos (500-800px) only at card or polaroid size; for a full-screen background, blur them.

## Post-processing and checks

```bash
python3 $S/prep_images.py <project>/assets/gen <project>/assets/photos --out <project>/assets/img [--blur] [--cutout]
python3 $S/prep_images.py --sheet <project>/assets/img --out <project>/qa/sheet_images.png
```

- It automatically crops off letterbox black bars, fits the long side to 2400px, and saves as JPG at quality 92.
- `--blur`: a blurred version for transitions and backgrounds (`_blur.jpg`)
- `--cutout`: a cutout of the person or subject with macOS Vision (`_cut.png`). It does not change the original pixels; it only makes the background transparent. It compiles with Swift once, the first time.
- Look at the sheet with Read and regenerate the following: finger or face anomalies, mixed-in lettering or logos, shots that stray from the palette, shots with a leftover letterbox.
- If the person's size and position differ from cutout to cutout, the image jumps when they are shown in sequence. Compute the head position and width from the alpha channel and match the sizes.

## How images go into the video

| Technique | Where to use it |
| --- | --- |
| Ken Burns (scale 1.08->1.18, slow movement) | In scenes that show a photo for a long time, when a still photo looks like a slide |
| 3D tilted card + clip wipe | Career and material cards, polaroids |
| Cutout + rim light (the cutout as a mask so the section palette's light falls only on the inner edge of the person) | Person reveals, name cards |
| Filling text with a photo (`background-clip: text`) | Opening keywords |
| Blurred and darkened (blur 6-10px, brightness 0.5) | Background texture behind text |
| Duotone and tint (`mix-blend-mode: color`) | When matching a scene's color to the palette |

When placing text over a photo, lay a dark gradient (scrim) on the text side. The code is in the "Photos" sections of `craft-engine.md`.
